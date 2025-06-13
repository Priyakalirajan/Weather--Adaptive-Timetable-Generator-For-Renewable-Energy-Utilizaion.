import os
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, send_from_directory
from werkzeug.utils import secure_filename
import pandas as pd
import random
import zipfile
from datetime import datetime
import requests
from fpdf import FPDF
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import time
from io import StringIO
import click
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()
logger.info("Environment variables loaded")

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['DOWNLOAD_FOLDER'] = 'downloads'
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Initialize app-level variables
app.subjects = []
app.labs = []
app.no_lab_subjects = []

logger.info("Flask app configured with:")
logger.info(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
logger.info(f"Download folder: {app.config['DOWNLOAD_FOLDER']}")

# Initialize LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

logger.info("Login manager initialized")

# User model
class User(UserMixin):
    def __init__(self, id, username, email):
        self.id = id
        self.username = username
        self.email = email

# Database setup
def get_db_connection():
    logger.debug("Connecting to database")
    conn = sqlite3.connect('users.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    logger.debug("Initializing database")
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      username TEXT UNIQUE NOT NULL,
                      email TEXT UNIQUE NOT NULL,
                      password TEXT NOT NULL)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS downloads
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      filename TEXT NOT NULL,
                      filepath TEXT NOT NULL,
                      downloaded_at DATETIME NOT NULL,
                      FOREIGN KEY(user_id) REFERENCES users(id))''')
        
        # Add subjects table
        c.execute('''CREATE TABLE IF NOT EXISTS subject_config
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      subjects TEXT NOT NULL,
                      labs TEXT NOT NULL,
                      no_lab_subjects TEXT NOT NULL,
                      FOREIGN KEY(user_id) REFERENCES users(id))''')
        conn.commit()
    logger.debug("Database initialized successfully")

@login_manager.user_loader
def load_user(user_id):
    logger.debug(f"Loading user with ID: {user_id}")
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = c.fetchone()
        if user:
            return User(id=user['id'], username=user['username'], email=user['email'])
        return None

# Ensure folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)
logger.info("Required directories created")

uploaded_files = []

# Weather API Configuration
API_KEY = os.getenv('OPENWEATHER_API_KEY', '052c7e3fa43e5b518cef8c171d287cf8')
if not API_KEY:
    raise ValueError("OPENWEATHER_API_KEY environment variable is not set")

CITY = os.getenv('WEATHER_CITY', 'madurai')
BASE_URL = "http://api.openweathermap.org/data/2.5/forecast"

# Global variables for subjects and labs (kept for backward compatibility)
subjects = []  # Will be populated from the form
labs = []  # Will be populated from the form
no_lab_subjects = []  # Will be populated from the form

class TimetablePDF(FPDF):
    def __init__(self):
        super().__init__(format='A3', orientation='L')  # Use A3 landscape for more space
        self.set_auto_page_break(auto=True, margin=15)
        
    def header(self):
        self.set_font('helvetica', 'B', 20)
        self.set_text_color(0, 0, 0)  # Black text
        self.cell(0, 20, 'Weather-Based Timetable', 0, 1, 'C')
        self.ln(15)

    def footer(self):
        self.set_y(-20)
        self.set_font('helvetica', 'I', 10)
        self.set_text_color(128, 128, 128)  # Gray text
        self.cell(0, 15, f'Page {self.page_no()}', 0, 0, 'C')

def create_pdf_timetable(timetable, filename):
    try:
        pdf = TimetablePDF()
        pdf.add_page()
        
        # Add title
        pdf.set_font('helvetica', 'B', 20)
        pdf.set_text_color(0, 0, 0)  # Black text
        pdf.cell(0, 15, 'Weather-Based Timetable', 0, 1, 'C')
        pdf.ln(10)
        
        # Calculate column widths
        page_width = pdf.w - 40
        first_col_width = 40
        col_width = (page_width - first_col_width) / (len(timetable.columns))
        row_height = 15
        
        # Define colors
        header_bg = (41, 128, 185)  # Dark blue for headers
        header_text = (255, 255, 255)  # White text for headers
        lab_bg = (231, 76, 60)  # Red for labs
        lab_text = (255, 255, 255)  # White text for labs
        lunch_bg = (46, 204, 113)  # Green for lunch
        lunch_text = (255, 255, 255)  # White text for lunch
        subject_bg = (241, 196, 15)  # Yellow for subjects
        subject_text = (0, 0, 0)  # Black text for subjects
        day_bg = (52, 152, 219)  # Light blue for day column
        day_text = (255, 255, 255)  # White text for day column
        
        # Add headers
        pdf.set_font('helvetica', 'B', 11)
        pdf.set_fill_color(*header_bg)
        pdf.set_text_color(*header_text)
        pdf.cell(first_col_width, row_height, 'Day', 1, 0, 'C', 1)
        
        for col in timetable.columns:
            pdf.cell(col_width, row_height, str(col), 1, 0, 'C', 1)
        pdf.ln()
        
        # Add rows
        pdf.set_font('helvetica', '', 10)
        for day in timetable.index:
            # Day column
            pdf.set_fill_color(*day_bg)
            pdf.set_text_color(*day_text)
            pdf.cell(first_col_width, row_height, str(day), 1, 0, 'C', 1)
            
            for col in timetable.columns:
                cell_value = str(timetable.loc[day, col])
                
                # Set colors based on cell content
                if 'Lab' in cell_value:
                    pdf.set_fill_color(*lab_bg)
                    pdf.set_text_color(*lab_text)
                    pdf.set_font('helvetica', 'B', 10)
                elif cell_value == 'Lunch Break':
                    pdf.set_fill_color(*lunch_bg)
                    pdf.set_text_color(*lunch_text)
                    pdf.set_font('helvetica', 'B', 10)
                else:
                    pdf.set_fill_color(*subject_bg)
                    pdf.set_text_color(*subject_text)
                    pdf.set_font('helvetica', '', 10)
                
                pdf.cell(col_width, row_height, cell_value, 1, 0, 'C', 1)
            pdf.ln()
        
        # Save PDF
        pdf.output(filename)
        return filename
        
    except Exception as e:
        raise Exception(f"Failed to create PDF: {str(e)}")

def validate_csv(filepath):
    try:
        df = pd.read_csv(filepath)
        required_cols = {'Date', 'Day', 'Condition', 'Temperature', 'Humidity', 'Wind Speed'}
        if not required_cols.issubset(df.columns):
            missing = required_cols - set(df.columns)
            raise ValueError(f"Missing columns: {', '.join(missing)}")
        return True
    except Exception as e:
        raise ValueError(f"Invalid CSV: {str(e)}")

# Time Management Functions
def generate_single_timetable(df, selected_subjects=None):
    # Track skipped labs and their intended subjects
    skipped_labs = []  # Format: {'day': day, 'subject': intended_subject}
    last_scheduled_subject = None
    used_lab_subjects = set()  # Track used lab subjects to avoid repetition
    
    # Get subjects from app-level variables
    all_subjects = app.subjects if hasattr(app, 'subjects') else []
    all_labs = app.labs if hasattr(app, 'labs') else []
    all_no_lab_subjects = app.no_lab_subjects if hasattr(app, 'no_lab_subjects') else []
    
    # Filter subjects if specified
    if selected_subjects:
        available_subjects = [s for s in all_subjects if s != 'free' and s in selected_subjects]
        lab_subjects = [s for s in all_subjects if s not in all_no_lab_subjects and s in selected_subjects]
    else:
        available_subjects = [s for s in all_subjects if s != 'free']
        lab_subjects = [s for s in all_subjects if s not in all_no_lab_subjects]
    
    # Filter out Sunday
    df = df[df['Day'] != 'Sunday']
    
    # Define time slots for the timetable
    morning_slots = ['9:00-10:00', '10:00-11:00', '11:00-12:00']
    lunch_slot = '12:00-1:00'
    afternoon_slots = ['1:00-2:00', '2:00-3:00', '3:00-4:00', '4:00-5:00']
    
    # Create empty timetable with all time slots
    all_slots = morning_slots + [lunch_slot] + afternoon_slots
    timetable = pd.DataFrame(index=df['Day'].unique(), columns=all_slots)
    
    # Set lunch break for all days
    timetable[lunch_slot] = 'Lunch Break'
    
    # Process each day
    for day in df['Day'].unique():
        day_data = df[df['Day'] == day].iloc[0]
        condition = day_data['Condition'].lower()
        
        # Skip labs on rainy or stormy days
        if 'rain' in condition or 'storm' in condition:
            # Select a lab subject that would have been scheduled
            intended_subject = None
            for sub in lab_subjects:
                if sub not in used_lab_subjects and sub != last_scheduled_subject:
                    intended_subject = sub
                    break
            
            if not intended_subject:
                # If all subjects have been used, reset the tracking
                used_lab_subjects.clear()
                intended_subject = random.choice([s for s in lab_subjects if s != last_scheduled_subject]) if lab_subjects else None
            
            if intended_subject:
                # Record the skipped lab
                skipped_labs.append({
                    'day': day,
                    'subject': intended_subject
                })
            
            # Schedule only regular subjects
            available_slots = morning_slots + afternoon_slots
            subjects_for_day = available_subjects.copy()
            random.shuffle(subjects_for_day)
            
            for slot in available_slots:
                if subjects_for_day:
                    timetable.loc[day, slot] = subjects_for_day.pop(0)
                else:
                    subjects_for_day = available_subjects.copy()
                    random.shuffle(subjects_for_day)
                    timetable.loc[day, slot] = subjects_for_day.pop(0)
        else:
            # Good weather day - can schedule labs
            labs_to_schedule = 1
            make_up_labs = []
            
            # Check if we have skipped labs to make up
            if skipped_labs:
                make_up_labs = [skipped_labs.pop(0)]
                labs_to_schedule += len(make_up_labs)
            
            # Schedule labs
            lab_subjects_to_use = []
            scheduled_slots = set()
            
            # Get subjects for scheduled labs
            if make_up_labs:
                lab_subjects_to_use.extend([item['subject'] for item in make_up_labs])
            
            # Add additional subjects if needed (avoiding repeats)
            while len(lab_subjects_to_use) < labs_to_schedule and lab_subjects:
                available_lab_subjects = [s for s in lab_subjects 
                                       if s not in used_lab_subjects 
                                       and s != last_scheduled_subject 
                                       and s not in lab_subjects_to_use]
                
                if not available_lab_subjects:
                    used_lab_subjects.clear()
                    available_lab_subjects = [s for s in lab_subjects 
                                           if s != last_scheduled_subject 
                                           and s not in lab_subjects_to_use]
                
                if available_lab_subjects:
                    subject = random.choice(available_lab_subjects)
                    lab_subjects_to_use.append(subject)
                    used_lab_subjects.add(subject)
            
            # Schedule the labs
            for lab_subject in lab_subjects_to_use:
                # Choose lab timing
                available_lab_slots = []
                if not any(slot in scheduled_slots for slot in morning_slots[:2]):
                    available_lab_slots.append(('morning', morning_slots[:2]))
                if not any(slot in scheduled_slots for slot in afternoon_slots[:2]):
                    available_lab_slots.append(('afternoon', afternoon_slots[:2]))
                
                if available_lab_slots:
                    time_of_day, slots = random.choice(available_lab_slots)
                    lab = random.choice(all_labs) if all_labs else "Lab"
                    
                    # Schedule 2-hour lab block with proper lab name
                    lab_name = f"{lab_subject} ({lab})"
                    timetable.loc[day, slots[0]] = lab_name
                    timetable.loc[day, slots[1]] = lab_name
                    scheduled_slots.update(slots)
                    last_scheduled_subject = lab_subject
            
            # Fill remaining slots with regular subjects
            available_slots = [slot for slot in (morning_slots + afternoon_slots) 
                             if slot not in scheduled_slots]
            subjects_for_day = available_subjects.copy()
            random.shuffle(subjects_for_day)
            
            for slot in available_slots:
                if subjects_for_day:
                    timetable.loc[day, slot] = subjects_for_day.pop(0)
                else:
                    subjects_for_day = available_subjects.copy()
                    random.shuffle(subjects_for_day)
                    timetable.loc[day, slot] = subjects_for_day.pop(0)
    
    return timetable

# Auth routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    logger.debug("Accessing register route")
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        logger.debug("Processing registration form")
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if 'terms' not in request.form:
            flash('You must accept the terms and conditions', 'error')
            return redirect(url_for('register'))
            
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('register'))
            
        # Server-side password validation
        if len(password) < 8:
            flash('Password must be at least 8 characters', 'error')
            return redirect(url_for('register'))
        if not any(c.isupper() for c in password):
            flash('Password must contain at least one uppercase letter', 'error')
            return redirect(url_for('register'))
        if not any(c.islower() for c in password):
            flash('Password must contain at least one lowercase letter', 'error')
            return redirect(url_for('register'))
        if not any(c.isdigit() for c in password):
            flash('Password must contain at least one number', 'error')
            return redirect(url_for('register'))
            
        hashed_password = generate_password_hash(password)
        
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                         (username, email, hashed_password))
                conn.commit()
            
            logger.info(f"User registered successfully: {username}")
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError as e:
            if 'username' in str(e):
                flash('Username already exists', 'error')
            elif 'email' in str(e):
                flash('Email already exists', 'error')
            else:
                flash('Registration error - please try again', 'error')
            return redirect(url_for('register'))
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            flash(f'Registration failed: {str(e)}', 'error')
            return redirect(url_for('register'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    logger.debug("Accessing login route")
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        logger.debug("Processing login form")
        username = request.form['username']
        password = request.form['password']
        
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = c.fetchone()
        
        if user and check_password_hash(user['password'], password):
            user_obj = User(id=user['id'], username=user['username'], email=user['email'])
            login_user(user_obj)
            logger.info(f"User logged in successfully: {username}")
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        else:
            logger.warning(f"Failed login attempt for username: {username}")
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'success')
    return redirect(url_for('index'))

@app.route('/configure_subjects', methods=['GET', 'POST'])
@login_required
def configure_subjects():
    global subjects, labs, no_lab_subjects
    
    if request.method == 'POST':
        # Process subjects with labs (split by newlines)
        subjects_text = request.form['subjects'].strip()
        labs_text = request.form['labs'].strip()
        no_lab_text = request.form['no_lab_subjects'].strip()
        
        # Convert to lists
        new_subjects = [s.strip() for s in subjects_text.split('\n') if s.strip()]
        new_labs = [s.strip() for s in labs_text.split('\n') if s.strip()]
        new_no_lab_subjects = [s.strip() for s in no_lab_text.split('\n') if s.strip()]
        
        if not new_subjects:
            flash('Please add at least one subject', 'error')
            return redirect(url_for('configure_subjects'))
            
        if not new_labs:
            flash('Please add at least one lab type', 'error')
            return redirect(url_for('configure_subjects'))
        
        try:
            # Save to database
            with get_db_connection() as conn:
                c = conn.cursor()
                # Delete existing configuration for this user
                c.execute("DELETE FROM subject_config WHERE user_id = ?", (current_user.id,))
                # Insert new configuration
                c.execute("""
                    INSERT INTO subject_config (user_id, subjects, labs, no_lab_subjects)
                    VALUES (?, ?, ?, ?)
                """, (
                    current_user.id,
                    '\n'.join(new_subjects),
                    '\n'.join(new_labs),
                    '\n'.join(new_no_lab_subjects)
                ))
                conn.commit()
            
            # Update both global and app-level variables
            subjects = new_subjects
            labs = new_labs
            no_lab_subjects = new_no_lab_subjects
            
            app.subjects = new_subjects
            app.labs = new_labs
            app.no_lab_subjects = new_no_lab_subjects
            
            flash('Subject configuration saved successfully!', 'success')
            return redirect(url_for('configure_subjects'))
            
        except Exception as e:
            flash(f'Error saving configuration: {str(e)}', 'error')
            return redirect(url_for('configure_subjects'))
    
    try:
        # Load existing configuration from database
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT subjects, labs, no_lab_subjects FROM subject_config WHERE user_id = ?", (current_user.id,))
            row = c.fetchone()
            
            if row:
                # Update both global and app-level variables
                subjects = [s.strip() for s in row[0].split('\n') if s.strip()]
                labs = [s.strip() for s in row[1].split('\n') if s.strip()]
                no_lab_subjects = [s.strip() for s in row[2].split('\n') if s.strip()]
                
                app.subjects = subjects
                app.labs = labs
                app.no_lab_subjects = no_lab_subjects
    except Exception as e:
        logger.error(f"Error loading subject configuration: {str(e)}")
    
    return render_template('subjects.html', 
                         subjects=subjects, 
                         labs=labs, 
                         no_lab_subjects=no_lab_subjects)

@app.route('/')
@app.route('/index')
def index():
    logger.debug("Accessing index route")
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'index.html')
    logger.debug(f"Template path: {template_path}")
    logger.debug(f"Template exists: {os.path.exists(template_path)}")
    if not os.path.exists(template_path):
        logger.warning("Template file not found")
        return "Welcome to Timetable Generator. Please configure the application."
    return render_template('index.html')

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        try:
            if 'file' not in request.files:
                flash('No file selected', 'error')
                return redirect(request.url)
            
            file = request.files['file']
            if file.filename == '':
                flash('No file selected', 'error')
                return redirect(request.url)
            
            if not file.filename.lower().endswith('.csv'):
                flash('Please upload a CSV file', 'error')
                return redirect(request.url)
            
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            try:
                # Save the file
                file.save(filepath)
                
                # Validate the CSV
                validate_csv(filepath)
                
                # Add to uploaded files list
                uploaded_files.append({
                    'name': filename,
                    'path': filepath,
                    'uploaded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'user_id': current_user.id
                })
                
                flash('File uploaded successfully!', 'success')
                return redirect(url_for('generate_timetable', filename=filename))
                
            except Exception as e:
                # Clean up the file if it exists
                if os.path.exists(filepath):
                    os.remove(filepath)
                flash(str(e), 'error')
                return redirect(request.url)
                
        except Exception as e:
            flash(f'Upload failed: {str(e)}', 'error')
            return redirect(request.url)
            
    return render_template('upload.html')

def get_weather_data():
    try:
        params = {
            "q": CITY,
            "appid": API_KEY,
            "units": "metric"
        }
        
        response = requests.get(BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data.get('list'):
            raise ValueError("No weather data available")
            
        return data
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to fetch weather data: {str(e)}")
    except ValueError as e:
        raise Exception(f"Weather data error: {str(e)}")

@app.route('/weather')
@login_required
def weather():
    try:
        data = get_weather_data()
        weather_data = []
        
        for forecast in data['list']:
            dt = datetime.strptime(forecast['dt_txt'], '%Y-%m-%d %H:%M:%S')
            weather_data.append({
                'Date': dt.date().isoformat(),
                'Day': dt.strftime('%A'),
                'Condition': forecast['weather'][0]['main'],
                'Temperature': round(forecast['main']['temp'], 1),
                'Humidity': forecast['main']['humidity'],
                'Wind Speed': round(forecast['wind']['speed'], 1)
            })

        df = pd.DataFrame(weather_data)
        daily = df.groupby(['Date', 'Day']).agg({
            'Temperature': 'mean',
            'Humidity': 'mean',
            'Wind Speed': 'mean',
            'Condition': lambda x: x.mode()[0]
        }).reset_index()
        
        daily['Temperature'] = daily['Temperature'].round(1)
        daily['Humidity'] = daily['Humidity'].round(0)
        daily['Wind Speed'] = daily['Wind Speed'].round(1)

        # Save the weather data to a CSV file
        weather_csv = os.path.join(app.config['UPLOAD_FOLDER'], 'weather_forecast.csv')
        daily.to_csv(weather_csv, index=False)
        
        # Add the file to uploaded_files list
        uploaded_files.append({
            'name': 'weather_forecast.csv',
            'path': weather_csv,
            'uploaded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'user_id': current_user.id
        })

        return render_template('weather.html', 
                             weather_data=daily.to_html(classes='table table-bordered table-hover', index=False))
        
    except Exception as e:
        flash(f'Failed to fetch weather: {str(e)}', 'error')
        return render_template('weather.html', weather_data=None)

@app.route('/generate_timetable/<filename>', methods=['GET', 'POST'])
@login_required
def generate_timetable(filename):
    try:
        # Load subjects from database if not already loaded
        if not hasattr(app, 'subjects') or not app.subjects:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT subjects, labs, no_lab_subjects FROM subject_config WHERE user_id = ?", (current_user.id,))
                row = c.fetchone()
                
                if row:
                    global subjects, labs, no_lab_subjects
                    subjects = [s.strip() for s in row[0].split('\n') if s.strip()]
                    labs = [s.strip() for s in row[1].split('\n') if s.strip()]
                    no_lab_subjects = [s.strip() for s in row[2].split('\n') if s.strip()]
                    
                    app.subjects = subjects
                    app.labs = labs
                    app.no_lab_subjects = no_lab_subjects
                else:
                    flash('Please configure subjects and labs first!', 'error')
                    return redirect(url_for('configure_subjects'))
        
        # Check if subjects are configured
        if not app.subjects or not app.labs:
            flash('Please configure subjects and labs first!', 'error')
            return redirect(url_for('configure_subjects'))

        # Check if the file exists
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Get selected subjects from form
        selected_subjects = request.form.getlist('subjects') if request.method == 'POST' else app.subjects.copy()
        
        if not selected_subjects:
            flash('Please select at least one subject', 'error')
            return redirect(url_for('generate_timetable', filename=filename))
            
        if not os.path.exists(filepath):
            error_msg = f'File not found: {filename}'
            logger.error(error_msg)
            if request.method == 'POST':
                flash(error_msg, 'error')
                return redirect(url_for('upload'))
            return error_msg, 404

        # Read and validate the CSV file
        try:
            df = pd.read_csv(filepath)
            df.columns = df.columns.str.strip()
            
            # Validate required columns
            required_cols = {'Date', 'Day', 'Condition', 'Temperature', 'Humidity', 'Wind Speed'}
            if not required_cols.issubset(df.columns):
                missing = required_cols - set(df.columns)
                error_msg = f"Missing columns in CSV: {', '.join(missing)}"
                logger.error(error_msg)
                if request.method == 'POST':
                    flash(error_msg, 'error')
                    return redirect(url_for('upload'))
                return error_msg, 400
        except Exception as e:
            error_msg = f'Error reading CSV file: {str(e)}'
            logger.error(error_msg)
            if request.method == 'POST':
                flash(error_msg, 'error')
                return redirect(url_for('upload'))
            return error_msg, 400

        # Create downloads directory if it doesn't exist
        download_dir = os.path.join(os.path.dirname(__file__), app.config['DOWNLOAD_FOLDER'])
        os.makedirs(download_dir, exist_ok=True)
        
        # Generate timetables
        zip_file = f'timetables_{filename.split(".")[0]}.zip'
        zip_path = os.path.join(download_dir, zip_file)
        
        # Remove existing zip file if it exists
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
                time.sleep(1)  # Give the system time to release the file
            except Exception as e:
                flash(f'Error removing existing zip file: {str(e)}', 'error')
                return redirect(url_for('upload'))
        
        # Create a temporary directory for PDFs
        temp_dir = os.path.join(app.config['DOWNLOAD_FOLDER'], 'temp_pdfs')
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            pdf_files = []
            for i in range(1, 7):
                try:
                    # Generate timetable with optional subject filter
                    timetable = generate_single_timetable(df, selected_subjects)
                    
                    # Create PDF
                    pdf_file = f'timetable_v{i}.pdf'
                    pdf_path = os.path.join(temp_dir, pdf_file)
                    create_pdf_timetable(timetable, pdf_path)
                    pdf_files.append(pdf_path)
                except Exception as e:
                    flash(f'Error generating timetable version {i}: {str(e)}', 'error')
                    # Clean up any created PDFs
                    for pdf in pdf_files:
                        try:
                            os.remove(pdf)
                        except:
                            pass
                    return redirect(url_for('upload'))

            # Create zip file with all PDFs
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for pdf_path in pdf_files:
                    if os.path.exists(pdf_path):
                        zipf.write(pdf_path, os.path.basename(pdf_path))
                        try:
                            os.remove(pdf_path)  # Clean up individual PDFs
                        except:
                            pass

            # Clean up temp directory
            try:
                os.rmdir(temp_dir)
            except:
                pass

        except Exception as e:
            flash(f'Error creating zip file: {str(e)}', 'error')
            # Clean up any remaining files
            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except:
                    pass
            return redirect(url_for('upload'))

        # Check if zip file was created successfully
        if not os.path.exists(zip_path):
            flash('Failed to create timetable files', 'error')
            return redirect(url_for('upload'))

        # Record the download in database
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO downloads (user_id, filename, filepath, downloaded_at)
                VALUES (?, ?, ?, ?)
            """, (current_user.id, zip_file, zip_path, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
        
        # Send the file
        try:
            response = send_file(
                zip_path,
                as_attachment=True,
                download_name=zip_file,
                mimetype='application/zip'
            )
            response.headers['X-Accel-Buffering'] = 'no'
            response.headers['Cache-Control'] = 'no-cache'
            response.headers['Connection'] = 'close'
            return response
        except Exception as e:
            flash(f'Error sending file: {str(e)}', 'error')
            return redirect(url_for('upload'))
            
    except Exception as e:
        flash(f'Failed to generate timetable: {str(e)}', 'error')
        return redirect(url_for('upload'))

@app.route('/download/<filename>')
@login_required
def download(filename):
    try:
        response = send_from_directory(
            app.config['DOWNLOAD_FOLDER'],
            filename,
            as_attachment=True
        )
        
        # Ensure the response is fully processed before returning
        response.call_on_close(lambda: print("Download completed"))
        return response
    except Exception as e:
        flash(f'Download failed: {str(e)}', 'error')
        return redirect(url_for('downloads'))

@app.route('/view')
@login_required
def view():
    return render_template('view.html', uploaded_files=uploaded_files)

@app.route('/sample.csv')
def sample_csv():
    """Generate and serve a sample CSV file"""
    sample_data = """Date,Day,Condition,Temperature,Humidity,Wind Speed
2023-06-01,Monday,Sunny,32.5,45,12.3
2023-06-02,Tuesday,Cloudy,28.7,60,8.5
2023-06-03,Wednesday,Rain,25.1,85,15.2
2023-06-04,Thursday,Sunny,30.2,50,10.1
2023-06-05,Friday,Cloudy,27.8,65,9.7
2023-06-06,Saturday,Storm,23.4,90,25.0
2023-06-07,Sunday,Sunny,31.0,48,11.5"""
    
    # Create in-memory file
    mem_file = StringIO()
    mem_file.write(sample_data)
    mem_file.seek(0)
    
    return send_file(
        mem_file,
        mimetype='text/csv',
        as_attachment=True,
        download_name='sample_weather_data.csv'
    )

@app.route('/downloads')
@login_required
def downloads():
    try:
        print(f"Fetching downloads for user {current_user.id}")  # Debug log
        
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT filename, downloaded_at 
                FROM downloads 
                WHERE user_id = ?
                ORDER BY downloaded_at DESC
            """, (current_user.id,))
            
            files = []
            for row in c.fetchall():
                filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], row[0])
                if os.path.exists(filepath):
                    files.append({
                        'name': row[0],
                        'downloaded_at': row[1],
                        'exists': True
                    })
                else:
                    print(f"File not found: {filepath}")  # Debug log
                    # Optionally clean up missing file records
                    c.execute("DELETE FROM downloads WHERE filename = ? AND user_id = ?", 
                             (row[0], current_user.id))
                    conn.commit()
        
        return render_template('downloads.html', downloaded_files=files)
        
    except Exception as e:
        print(f"Error in downloads route: {str(e)}")  # Debug log
        flash('Error loading downloads. Please try again.', 'error')
        return render_template('downloads.html', downloaded_files=[])

@app.cli.command('generate_timetable')
@click.argument('filename')
def cli_generate_timetable(filename):
    """Generate timetable from command line"""
    with app.app_context():
        try:
            result = generate_timetable(filename)
            if isinstance(result, str) and result.startswith('Error'):
                click.echo(result)
                return 1
            click.echo(f"Successfully generated timetable from {filename}")
            return 0
        except Exception as e:
            click.echo(f"Error: {str(e)}")
            return 1

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
