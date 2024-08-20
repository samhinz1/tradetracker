import logging
from flask import Flask, flash
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
import os
from db import db  # Import the db instance from the separate db.py module

# Set environment variables
os.environ['FLASK_ENV'] = 'development'
os.environ['FLASK_DEBUG'] = '1'

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'  # Replace with a secure key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize extensions with app
db.init_app(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'
bcrypt = Bcrypt(app)

# Import models and routes after app and db initialization to avoid circular imports
from models import User
from routes import *

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

if __name__ == "__main__":
    app.run(debug=True)
