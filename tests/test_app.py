"""
Test Flask Application
======================
Tests for Flask app routes and functionality
"""

import pytest
from flask import url_for


class TestPublicRoutes:
    """Test public routes that don't require authentication."""
    
    def test_index_page(self, client):
        """Test home page loads correctly."""
        response = client.get('/')
        assert response.status_code == 200
        assert b'AI-NIDS' in response.data or b'Network Intrusion' in response.data
    
    def test_login_page(self, client):
        """Test login page loads correctly."""
        response = client.get('/auth/login')
        assert response.status_code == 200
        assert b'login' in response.data.lower() or b'sign in' in response.data.lower()
    
    def test_register_page(self, client):
        """Test registration page loads correctly."""
        response = client.get('/auth/register')
        assert response.status_code == 200
    
    def test_health_endpoint(self, client):
        """Test health check endpoint."""
        response = client.get('/api/v1/health')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['status'] == 'healthy'


class TestAuthentication:
    """Test authentication functionality."""
    
    def test_login_success(self, app, client):
        """Test successful login."""
        from app.models.database import db, User
        
        with app.app_context():
            # Create user
            user = User(username='logintest', email='login@test.com')
            user.set_password('password123')
            db.session.add(user)
            db.session.commit()
            
            # Login
            response = client.post('/auth/login', data={
                'username': 'logintest',
                'password': 'password123'
            }, follow_redirects=True)
            
            assert response.status_code == 200
            
            # Cleanup
            db.session.delete(user)
            db.session.commit()
    
    def test_login_failure(self, client):
        """Test failed login with wrong credentials."""
        response = client.post('/auth/login', data={
            'username': 'wronguser',
            'password': 'wrongpassword'
        }, follow_redirects=True)
        
        assert b'invalid' in response.data.lower() or b'error' in response.data.lower()
    
    def test_logout(self, auth_client):
        """Test logout functionality."""
        response = auth_client.get('/auth/logout', follow_redirects=True)
        assert response.status_code == 200


class TestProtectedRoutes:
    """Test routes that require authentication."""
    
    def test_dashboard_requires_auth(self, client):
        """Test dashboard redirects to login when not authenticated."""
        response = client.get('/dashboard', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.location or '/auth' in response.location
    
    def test_dashboard_access(self, auth_client):
        """Test dashboard access when authenticated."""
        response = auth_client.get('/dashboard')
        assert response.status_code == 200
    
    def test_alerts_page(self, auth_client):
        """Test alerts page access."""
        response = auth_client.get('/alerts')
        assert response.status_code == 200
    
    def test_analytics_page(self, auth_client):
        """Test analytics page access."""
        response = auth_client.get('/analytics')
        assert response.status_code == 200


class TestAPI:
    """Test API endpoints."""
    
    def test_api_analyze_requires_auth(self, client, sample_network_flow):
        """Test API analyze endpoint requires authentication."""
        response = client.post('/api/v1/analyze', json=sample_network_flow)
        assert response.status_code == 401
    
    def test_api_alerts_list(self, auth_client):
        """Test API alerts listing."""
        response = auth_client.get('/api/v1/alerts')
        assert response.status_code == 200
        json_data = response.get_json()
        assert 'alerts' in json_data or 'data' in json_data
    
    def test_api_stats(self, auth_client):
        """Test API stats endpoint."""
        response = auth_client.get('/api/v1/stats')
        assert response.status_code == 200


class TestErrorHandling:
    """Test error handling."""
    
    def test_404_page(self, client):
        """Test 404 error page."""
        response = client.get('/nonexistent-page')
        assert response.status_code == 404
    
    def test_invalid_json(self, auth_client):
        """Test invalid JSON handling."""
        response = auth_client.post(
            '/api/v1/analyze',
            data='not json',
            content_type='application/json'
        )
        assert response.status_code in [400, 422]


def test_production_requires_secret_key_and_admin_password(monkeypatch):
    from app import create_app

    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.setenv('ADMIN_PASSWORD', 'a-strong-admin-password')
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app('production')

    monkeypatch.setenv('SECRET_KEY', 's' * 48)
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    with pytest.raises(RuntimeError, match='ADMIN_PASSWORD'):
        create_app('production')


def test_production_bootstraps_secure_admin_and_disables_seeded_defaults(
    monkeypatch, tmp_path
):
    from app import create_app, db
    from app.models.database import User
    from config import ProductionConfig

    monkeypatch.setenv('SECRET_KEY', 's' * 48)
    monkeypatch.setenv('ADMIN_PASSWORD', 'a-strong-admin-password')
    monkeypatch.setenv('ADMIN_USERNAME', 'deployed-admin')
    monkeypatch.setenv('ADMIN_EMAIL', 'admin@example.com')
    monkeypatch.setattr(
        ProductionConfig,
        'SQLALCHEMY_DATABASE_URI',
        f"sqlite:///{(tmp_path / 'production.db').as_posix()}",
    )

    app = create_app('production')
    with app.app_context():
        admin = User.query.filter_by(username='deployed-admin').one()
        assert admin.check_password('a-strong-admin-password')
        assert admin.role == 'admin'
        assert admin.is_active

        legacy_admin = User(username='legacy-admin', email='legacy@example.com', role='admin')
        legacy_admin.set_password('admin123')
        legacy_demo = User(username='legacy-demo', email='demo@example.com', role='admin')
        legacy_demo.set_password('demo123')
        db.session.add_all([legacy_admin, legacy_demo])
        db.session.commit()

    app = create_app('production')
    with app.app_context():
        assert not User.query.filter_by(username='legacy-admin').one().is_active
        assert not User.query.filter_by(username='legacy-demo').one().is_active
        assert User.query.filter_by(username='deployed-admin').one().is_active


def test_demo_seeder_refuses_production(monkeypatch):
    from utils.seed_data import seed_all

    monkeypatch.setenv('FLASK_ENV', 'production')
    with pytest.raises(RuntimeError, match='disabled in production'):
        seed_all(flows=0, alerts=0)
