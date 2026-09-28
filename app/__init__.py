"""
AI-NIDS Flask Application Factory
==================================
Main application package initialization.
"""

import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_cors import CORS

from config import config, Config

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

# Configure login manager
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'


def create_app(config_name=None):
    """
    Application factory function.
    
    Args:
        config_name: Configuration name ('development', 'testing', 'production')
    
    Returns:
        Flask application instance
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    # Create Flask app
    app = Flask(__name__)
    
    # Load configuration
    app.config.from_object(config[config_name])
    if config_name == 'production':
        secret_key = os.environ.get('SECRET_KEY', '')
        admin_password = os.environ.get('ADMIN_PASSWORD', '')
        if len(secret_key) < 32 or secret_key in {
            'your-super-secret-key-change-in-production',
            'ai-nids-super-secret-key-change-in-production',
            'ai-nids-production-secret-key-2024',
            'change-me-in-production',
        }:
            raise RuntimeError('Production requires SECRET_KEY with at least 32 characters.')
        if len(admin_password) < 12:
            raise RuntimeError('Production requires ADMIN_PASSWORD with at least 12 characters.')
        app.config['SECRET_KEY'] = secret_key

    config[config_name].init_app(app)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    # Setup logging
    setup_logging(app)
    
    # Register blueprints
    register_blueprints(app)
    
    # Register error handlers
    register_error_handlers(app)
    
    # Create database tables
    with app.app_context():
        db.create_all()
        
        if config_name == 'production':
            bootstrap_production_admin(app)
    
    # Register CLI commands
    register_cli_commands(app)
    
    # Register custom Jinja filters
    register_template_filters(app)
    
    app.logger.info(f'AI-NIDS initialized in {config_name} mode')
    
    return app


def bootstrap_production_admin(app):
    """Create the initial production admin from explicitly configured secrets."""
    from app.models.database import User

    username = os.environ.get('ADMIN_USERNAME', 'admin')
    email = os.environ.get('ADMIN_EMAIL', 'admin@ainids.local')
    password = os.environ['ADMIN_PASSWORD']
    known_defaults = ('admin123', 'demo123')

    for user in User.query.filter_by(role='admin').all():
        if any(user.check_password(default) for default in known_defaults):
            user.is_active = False
            app.logger.warning('Disabled admin account with a known default password: %s', user.username)

    admin = User.query.filter_by(username=username).first()
    if admin is None:
        admin = User(username=username, email=email, role='admin')
        admin.set_password(password)
        db.session.add(admin)
        app.logger.info('Created production admin from configured credentials')
    elif any(admin.check_password(default) for default in known_defaults):
        admin.email = email
        admin.role = 'admin'
        admin.is_active = True
        admin.set_password(password)
        app.logger.warning('Replaced a known default password for production admin: %s', username)

    db.session.commit()


def setup_logging(app):
    """Configure application logging."""
    log_level = getattr(logging, app.config.get('LOG_LEVEL', 'INFO'))
    log_format = app.config.get('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=log_format
    )
    
    # Configure file handler if log file specified
    log_file = app.config.get('LOG_FILE')
    if log_file:
        from pathlib import Path
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter(log_format))
        app.logger.addHandler(file_handler)


def register_blueprints(app):
    """Register all application blueprints."""
    from app.routes.dashboard import dashboard_bp
    from app.routes.auth import auth_bp
    from app.routes.api import api_bp
    from app.routes.alerts import alerts_bp
    from app.routes.analytics import analytics_bp
    from app.routes.ai_models import ai_models_bp
    
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(api_bp, url_prefix='/api/v1')
    app.register_blueprint(alerts_bp, url_prefix='/alerts')
    app.register_blueprint(analytics_bp, url_prefix='/analytics')
    app.register_blueprint(ai_models_bp)
    
    # Exempt API blueprint from CSRF protection
    csrf.exempt(api_bp)


def register_error_handlers(app):
    """Register error handlers."""
    from flask import render_template, jsonify, request
    
    @app.errorhandler(400)
    def bad_request(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Bad Request', 'message': str(error)}), 400
        return render_template('errors/400.html'), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Unauthorized', 'message': 'Authentication required'}), 401
        return render_template('errors/401.html'), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Forbidden', 'message': 'Access denied'}), 403
        return render_template('errors/403.html'), 403
    
    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not Found', 'message': 'Resource not found'}), 404
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal Server Error', 'message': 'An unexpected error occurred'}), 500
        return render_template('errors/500.html'), 500


def register_cli_commands(app):
    """Register CLI commands."""
    
    @app.cli.command('init-db')
    def init_db():
        """Initialize the database."""
        db.create_all()
        print('Database initialized.')
    
    @app.cli.command('create-admin')
    def create_admin():
        """Create admin user."""
        from app.models.database import User
        
        username = input('Username: ')
        email = input('Email: ')
        password = input('Password: ')
        
        user = User(username=username, email=email, role='admin')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f'Admin user {username} created.')
    
    @app.cli.command('train-models')
    def train_models():
        """Train ML models."""
        from ml.training.trainer import ModelTrainer
        trainer = ModelTrainer()
        trainer.train_all()
        print('Models trained successfully.')


def register_template_filters(app):
    """Register custom Jinja2 template filters."""
    
    @app.template_filter('format_number')
    def format_number(value):
        """Format number with thousands separator."""
        try:
            return '{:,}'.format(int(value or 0))
        except (ValueError, TypeError):
            return '0'
    
    @app.template_filter('number_format')
    def number_format(value):
        """Format number with thousands separator (alias)."""
        try:
            return '{:,}'.format(int(value or 0))
        except (ValueError, TypeError):
            return '0'
    
    @app.template_filter('abs_value')
    def abs_value(value):
        """Return absolute value."""
        try:
            return abs(float(value or 0))
        except (ValueError, TypeError):
            return 0
    
    @app.template_filter('clamp')
    def clamp(value, min_val=0, max_val=100):
        """Clamp a value between min and max."""
        try:
            val = float(value or 0)
            return max(min_val, min(max_val, val))
        except (ValueError, TypeError):
            return min_val
    
    @app.template_filter('percentage')
    def percentage(value, total=100):
        """Calculate percentage with clamping to 100."""
        try:
            if total == 0:
                return 0
            pct = (float(value or 0) / float(total)) * 100
            return min(100, max(0, pct))
        except (ValueError, TypeError):
            return 0
