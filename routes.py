from flask import render_template, request, redirect, url_for, flash, jsonify, session
from app import app, db, bcrypt
from forms import RegistrationForm, LoginForm
from models import User
from flask_login import login_user, logout_user, login_required, current_user
import os
import pandas as pd
import sqlite3
from utils import *
from datetime import datetime, date
from alpha_vantage.timeseries import TimeSeries
from uuid import UUID
import uuid
import json

DB_FILE_PATH = 'instance/site.db'  # Adjust this to your actual database path

def get_db_connection():
    conn = sqlite3.connect(DB_FILE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row  # Set the row factory to sqlite3.Row
    return conn

def parse_date(date_str):
    if isinstance(date_str, (datetime, date)):
        return date_str

    date_formats = ["%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"]
    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            app.logger.debug(f"Successfully parsed date: {parsed_date} from {date_str} using format {fmt}")
            return parsed_date
        except ValueError:
            app.logger.debug(f"Failed to parse date: {date_str} using format {fmt}")
            continue

    app.logger.error(f"Date format for {date_str} is not supported")
    return None  # Return None if parsing fails

def get_latest_stock_price(symbol, api_key):
    ts = TimeSeries(key=api_key, output_format='pandas')
    data, meta_data = ts.get_quote_endpoint(symbol)
    return data['05. price'].iloc[0]

def update_last_prices():
    api_key = 'QJ85FALN2NTD1GUX'  # Replace with your actual Alpha Vantage API key
    
    with get_db_connection() as conn:
        open_trades_df = pd.read_sql_query("SELECT * FROM open_trades WHERE user_id = ?", conn, params=(current_user.id,))
        
        for index, row in open_trades_df.iterrows():
            symbol = row['Market']
            try:
                latest_price = get_latest_stock_price(symbol, api_key)
                app.logger.debug(f"Latest price for {symbol}: {latest_price}")
                open_trades_df.at[index, 'last_price'] = latest_price
            except Exception as e:
                app.logger.error(f"Error fetching latest price for {symbol}: {e}")
                continue  # Skip this symbol and continue with the next
        
        # Update the database with the new prices
        open_trades_df.to_sql('open_trades', conn, if_exists='replace', index=False)
        app.logger.info("Updated open trades with the latest prices.")

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/journal')
@login_required
def journal():
    conn = get_db_connection()
    trades_df = pd.read_sql_query("SELECT * FROM trades WHERE user_id = ?", conn, params=(current_user.id,))
    conn.close()
    
    filter_type = request.args.get('filter', 'all')
    filtered_trades_df = filter_data(trades_df, filter_type)

    if filtered_trades_df.empty:
        message = f"No trades available for {filter_type.replace('_', ' ').title()} setup"
        return render_template('journal.html', equity_curve="", daily_pl="", calendar_data="", overview={}, trade_stats={}, trade_log=[], filter_type=filter_type, message=message)

    analysis_results = perform_analysis(filtered_trades_df)
    equity_curve_html, daily_pl_html, overview, trade_stats, trade_log_dict = create_dashboard(*analysis_results, filtered_trades_df)
    return render_template('journal.html', equity_curve=equity_curve_html, daily_pl=daily_pl_html, calendar_data="", overview=overview, trade_stats=trade_stats, trade_log=trade_log_dict, filter_type=filter_type, message="")

@app.route('/closed_trades', methods=['GET'])
@login_required
def trade_log():
    conn = get_db_connection()
    trades_df = pd.read_sql_query("SELECT * FROM trades WHERE user_id = ?", conn, params=(current_user.id,))
    conn.close()

    # Ensure numeric conversion
    trades_df['Comm'] = pd.to_numeric(trades_df['Comm'], errors='coerce').fillna(0.0)
    trades_df['Commissions'] = pd.to_numeric(trades_df['Commissions'], errors='coerce').fillna(0.0)

    trade_log_dict = trades_df.to_dict(orient='records')
    return render_template('trade_log.html', trade_log=trade_log_dict)

@app.route('/calendar')
@login_required
def calendar():
    return render_template('calendar.html')

@app.route('/overview')
@login_required
def overview_trade_statistics():
    conn = get_db_connection()
    trades_df = pd.read_sql_query("SELECT * FROM trades WHERE user_id = ?", conn, params=(current_user.id,))
    conn.close()

    filter_type = request.args.get('filter', 'all')
    filtered_trades_df = filter_data(trades_df, filter_type)

    if filtered_trades_df.empty:
        message = f"No trades available for {filter_type.replace('_', ' ').title()} setup"
        return render_template('overview_trade_statistics.html', overview={}, trade_stats={}, filter_type=filter_type, message=message)

    analysis_results = perform_analysis(filtered_trades_df)
    _, _, overview, trade_stats, _ = create_dashboard(*analysis_results, filtered_trades_df)
    return render_template('overview_trade_statistics.html', overview=overview, trade_stats=trade_stats, filter_type=filter_type, message="")

@app.route('/equity_curve')
@login_required
def equity_curve():
    conn = get_db_connection()
    trades_df = pd.read_sql_query("SELECT * FROM trades WHERE user_id = ?", conn, params=(current_user.id,))
    conn.close()

    filter_type = request.args.get('filter', 'all')
    filtered_trades_df = filter_data(trades_df, filter_type)

    if filtered_trades_df.empty:
        message = f"No trades available for {filter_type.replace('_', ' ').title()} setup"
        return render_template('equity_curve.html', equity_curve="", daily_pl="", filter_type=filter_type, message=message)

    analysis_results = perform_analysis(filtered_trades_df)
    equity_curve_html, daily_pl_html, _, _, _ = create_dashboard(*analysis_results, filtered_trades_df)
    return render_template('equity_curve.html', equity_curve=equity_curve_html, daily_pl=daily_pl_html, filter_type=filter_type, message="")

@app.route('/upload_data')
@login_required
def upload_data():
    return render_template('upload_data.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            flash('That email is taken. Please choose a different one.', 'danger')
        else:
            hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
            user = User(username=form.username.data, email=form.email.data, password=hashed_password)
            db.session.add(user)
            db.session.commit()
            flash('Your account has been created! You are now able to log in', 'success')
            return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            return redirect(url_for('overview_trade_statistics'))
        else:
            flash('Login Unsuccessful. Please check email and password', 'danger')
    return render_template('login.html', title='Login', form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_file():
    if request.method == 'POST':
        try:
            if 'file' not in request.files:
                flash('No file part', 'danger')
                return redirect(request.url)
            file = request.files['file']
            if file.filename == '':
                flash('No selected file', 'danger')
                return redirect(request.url)
            if file:
                file_path = save_file_path(current_user.id, file.filename)
                file.save(file_path)
                store_last_file_path(current_user.id, file_path)

                # Read and process CSV data
                trades_df = pd.read_csv(file_path, skiprows=7, on_bad_lines='skip')
                trades_df.columns = trades_df.columns.str.strip()

                column_mapping = {
                    'Closing Ref': 'Closing_Ref',
                    'Closed': 'Closed',
                    'Opening Ref': 'Opening_Ref',
                    'Opened': 'Opened',
                    'Market': 'Market',
                    'Period': 'Period',
                    'Direction': 'Direction',
                    'Size': 'Size',
                    'Opening': 'Opening',
                    'Closing': 'Closing',
                    'Trade Ccy.': 'Trade_Ccy',
                    'P/L': 'PL',
                    'Funding': 'Funding',
                    'Borrowing': 'Borrowing',
                    'Dividends': 'Dividends',
                    'LR Prem.': 'LR_Prem',
                    'Others': 'Others',
                    'Comm. Ccy.': 'Comm_Ccy',
                    'Comm.': 'Comm',
                    'Total': 'Total'
                }

                trades_df.rename(columns=column_mapping, inplace=True)

                if 'PL' in trades_df.columns and trades_df['PL'].dtype == object:
                    trades_df['PL'] = trades_df['PL'].str.replace(',', '').astype(float).round(1)
                elif 'PL' in trades_df.columns:
                    trades_df['PL'] = trades_df['PL'].astype(float).round(1)
                else:
                    trades_df['PL'] = 0.0

                if 'Total' in trades_df.columns and trades_df['Total'].dtype == object:
                    trades_df['Total'] = trades_df['Total'].str.replace(',', '').astype(float)
                elif 'Total' in trades_df.columns:
                    trades_df['Total'] = trades_df['Total'].astype(float)
                else:
                    trades_df['Total'] = trades_df['PL']

                if 'Comm' not in trades_df.columns:
                    trades_df['Comm'] = trades_df['Total'] - trades_df['PL']
                trades_df['Comm'] = trades_df['Comm'].astype(float).round(1)

                if 'Commissions' in trades_df.columns:
                    trades_df['Commissions'] = trades_df['Commissions'].astype(float).round(1)
                else:
                    trades_df['Commissions'] = 0.0

                if 'Closing' in trades_df.columns and 'Opening' in trades_df.columns:
                    trades_df['P/L %'] = ((trades_df['Closing'] - trades_df['Opening']) / trades_df['Opening']) * 100
                    trades_df['P/L %'] = trades_df['P/L %'].round(2)
                else:
                    trades_df['P/L %'] = 0.0

                if 'Closed' in trades_df.columns:
                    trades_df['Closed'] = trades_df['Closed'].apply(parse_date)

                if 'setup_type' not in trades_df.columns:
                    trades_df['setup_type'] = ''
                trades_df['setup_type'] = trades_df['setup_type'].fillna('')

                if 'note' not in trades_df.columns:
                    trades_df['note'] = ''
                trades_df['note'] = trades_df['note'].fillna('')

                trades_df['user_id'] = current_user.id  # Associate trade with current user

                # Store data in the database
                conn = get_db_connection()
                existing_trades_df = pd.read_sql_query("SELECT * FROM trades WHERE user_id = ?", conn, params=(current_user.id,))
                updated_trades_df = pd.concat([existing_trades_df, trades_df])
                updated_trades_df.to_sql('trades', conn, if_exists='append', index=False)  # Changed to append
                conn.close()

                # Render the journal with updated data
                filter_type = 'all'
                filtered_trades_df = filter_data(updated_trades_df, filter_type)
                analysis_results = perform_analysis(filtered_trades_df)
                equity_curve_html, daily_pl_html, overview, trade_stats, trade_log_dict = create_dashboard(*analysis_results, filtered_trades_df)
                return render_template('journal.html', equity_curve=equity_curve_html, daily_pl=daily_pl_html, calendar_data="", overview=overview, trade_stats=trade_stats, trade_log=trade_log_dict, filter_type=filter_type)
        except Exception as e:
            flash('An error occurred while processing the file. Please ensure the data is correctly formatted and try again.', 'danger')
            app.logger.error(f"Error during file upload: {e}")
            return redirect(request.url)
    return render_template('upload_data.html')

@app.route('/merge', methods=['POST'])
@login_required
def merge_file():
    try:
        if 'file' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        
        new_file_path = save_file_path(current_user.id, file.filename)
        file.save(new_file_path)

        # Load new data
        new_trades_df = pd.read_csv(new_file_path, skiprows=7, on_bad_lines='skip')
        new_trades_df.columns = new_trades_df.columns.str.strip()

        column_mapping = {
            'Closing Ref': 'Closing_Ref',
            'Closed': 'Closed',
            'Opening Ref': 'Opening_Ref',
            'Opened': 'Opened',
            'Market': 'Market',
            'Period': 'Period',
            'Direction': 'Direction',
            'Size': 'Size',
            'Opening': 'Opening',
            'Closing': 'Closing',
            'Trade Ccy.': 'Trade_Ccy',
            'P/L': 'PL',
            'Funding': 'Funding',
            'Borrowing': 'Borrowing',
            'Dividends': 'Dividends',
            'LR Prem.': 'LR_Prem',
            'Others': 'Others',
            'Comm. Ccy.': 'Comm_Ccy',
            'Comm.': 'Comm',
            'Total': 'Total'
        }

        new_trades_df.rename(columns=column_mapping, inplace=True)

        new_trades_df['PL'] = new_trades_df['PL'].str.replace(',', '').astype(float).round(1)
        new_trades_df['Total'] = new_trades_df['Total'].str.replace(',', '').astype(float)
        new_trades_df['Comm'] = new_trades_df.get('Comm', new_trades_df['Total'] - new_trades_df['PL']).round(1)
        new_trades_df['P/L %'] = ((new_trades_df['Closing'] - new_trades_df['Opening']) / new_trades_df['Opening']) * 100
        new_trades_df['P/L %'] = new_trades_df['P/L %'].round(2)

        # Ensure dates are parsed correctly
        new_trades_df['Closed'] = new_trades_df['Closed'].apply(parse_date)
        new_trades_df['Opened'] = new_trades_df['Opened'].apply(parse_date)

        new_trades_df['setup_type'] = new_trades_df.get('setup_type', 'No Setup selected')
        new_trades_df['note'] = new_trades_df.get('note', '')
        new_trades_df['Commissions'] = new_trades_df.get('Commissions', '')
        new_trades_df['user_id'] = current_user.id
        new_trades_df['id'] = [str(uuid.uuid4()) for _ in range(len(new_trades_df))]

        # Load existing data
        conn = get_db_connection()
        existing_trades_df = pd.read_sql_query("SELECT * FROM trades WHERE user_id = ?", conn, params=(current_user.id,))
        conn.close()

        # Merge new trades with existing trades
        combined_trades_df = pd.concat([existing_trades_df, new_trades_df]).drop_duplicates(subset=['Closing_Ref', 'Opening_Ref'], keep='first')

        # Ensure all datetime fields are converted to strings before storing in SQLite
        combined_trades_df['Closed'] = combined_trades_df['Closed'].astype(str)
        combined_trades_df['Opened'] = combined_trades_df['Opened'].astype(str)

        # Store combined data in the database
        conn = get_db_connection()
        combined_trades_df.to_sql('trades', conn, if_exists='replace', index=False)  # Changed to append
        conn.close()

        flash('File merged successfully', 'success')
        return redirect(url_for('trade_log'))
    except Exception as e:
        app.logger.error(f"Error merging file: {e}")
        flash('An error occurred while merging the file', 'danger')
        return redirect(request.url)


@app.route('/save_trade_log', methods=['POST'])
@login_required
def save_trade_log():
    try:
        conn = get_db_connection()
        trades_df = pd.read_sql_query("SELECT * FROM trades WHERE user_id = ?", conn, params=(current_user.id,))

        # Log the form data for debugging
        app.logger.debug(f"Form data: {request.form}")

        trade_id = request.form.get('trade_id')
        if not trade_id:
            raise ValueError("Trade ID is missing in the form data")
        
        # Find the index of the trade with the given trade_id
        index = trades_df[trades_df['id'] == trade_id].index
        if index.empty:
            raise ValueError("Trade ID not found in the database")
        index = index[0]

        # Update only the specific fields
        if 'setup_type' in request.form:
            trades_df.at[index, 'setup_type'] = request.form['setup_type']
        if 'note' in request.form:
            trades_df.at[index, 'note'] = request.form['note']

        trades_df.to_sql('trades', conn, if_exists='replace', index=False)
        conn.close()

        return jsonify({'status': 'success'})
    except ValueError as ve:
        flash(f'Invalid data: {ve}', 'danger')
        app.logger.error(f"ValueError during trade log save: {ve}")
        return jsonify({'status': 'error', 'message': str(ve)})
    except Exception as e:
        flash('An error occurred while saving the trade log. Please try again.', 'danger')
        app.logger.error(f"Error during trade log save: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while saving the trade log.'})



@app.route('/calendar_data')
@login_required
def calendar_data():
    conn = get_db_connection()
    trades_df = pd.read_sql_query("SELECT * FROM trades WHERE user_id = ?", conn, params=(current_user.id,))
    conn.close()

    trades_df['Closed'] = trades_df['Closed'].apply(parse_date)
    app.logger.debug(f"Parsed Closed Dates: {trades_df['Closed'].head()}")  # Log parsed dates

    daily_pl = trades_df.groupby('Closed')['Total'].sum().reset_index()
    daily_pl['Closed'] = pd.to_datetime(daily_pl['Closed'])
    app.logger.debug(f"Daily P/L DataFrame: {daily_pl.head()}")  # Log daily P/L data

    daily_pl['Week'] = daily_pl['Closed'].dt.to_period('W').apply(lambda r: r.start_time)
    weekly_totals = daily_pl.groupby('Week')['Total'].sum().reset_index()
    app.logger.debug(f"Weekly Totals DataFrame: {weekly_totals.head()}")  # Log weekly totals

    daily_pl['Closed'] = daily_pl['Closed'].astype(str)
    weekly_totals['Week'] = weekly_totals['Week'].astype(str)
    weekly_totals['Saturday'] = pd.to_datetime(weekly_totals['Week']) + pd.DateOffset(days=5)

    events = []
    for _, row in daily_pl.iterrows():
        event_class = 'fc-event-positive' if row['Total'] >= 0 else 'fc-event-negative'
        events.append({
            'title': f"${row['Total']:,.2f}",
            'start': row['Closed'],
            'className': event_class
        })

    for _, row in weekly_totals.iterrows():
        events.append({
            'title': f"Total: ${row['Total']:,.2f}",
            'start': row['Saturday'].strftime('%Y-%m-%d'),
            'display': 'background',
            'backgroundColor': 'rgba(46, 255, 171, 0.2)',
            'borderColor': 'rgba(46, 255, 171, 0.5)',
            'textColor': '#2effab'
        })

    app.logger.debug(f"Events JSON: {events}")  # Log events JSON
    return jsonify(events)



@app.route('/add_trade', methods=['POST'])
@login_required
def add_trade():
    try:
        app.logger.debug('Add trade function called')
        
        # Log request form data
        app.logger.debug(f"Request form data: {request.form}")

        def parse_and_format_datetime(date_str, time_str):
            # If time is empty, set it to '00:00:00'
            if not time_str:
                time_str = '00:00:00'
            combined_str = f"{date_str} {time_str}"
            date_formats = ["%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y", "%Y-%m-%d"]
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(combined_str, fmt)
                    return parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
            return None

        new_trade = {
            'id': str(uuid.uuid4()),  # Generate a new UUID for the trade
            'Closing_Ref': request.form.get('Closing_Ref', ''),
            'Closed': parse_and_format_datetime(request.form.get('closed-date', ''), request.form.get('closed-time', '')),
            'Opening_Ref': request.form.get('Opening_Ref', ''),
            'Opened': parse_and_format_datetime(request.form.get('opened-date', ''), request.form.get('opened-time', '')),
            'Market': request.form.get('Market', ''),
            'Period': request.form.get('Period', ''),
            'Direction': request.form.get('Direction', ''),
            'Size': request.form.get('Size', 0.0, type=float),
            'Opening': request.form.get('Opening', 0.0, type=float),
            'Closing': request.form.get('Closing', 0.0, type=float),
            'Trade_Ccy': request.form.get('Trade_Ccy', ''),
            'Total': request.form.get('Total', 0.0, type=float),  # P/L on form maps to Total in the database
            'Funding': request.form.get('Funding', 0.0, type=float),
            'Borrowing': request.form.get('Borrowing', 0.0, type=float),
            'Dividends': request.form.get('Dividends', 0.0, type=float),
            'LR_Prem': request.form.get('LR_Prem', 0.0, type=float),
            'Others': request.form.get('Others', 0.0, type=float),
            'Comm_Ccy': request.form.get('Comm_Ccy', ''),
            'Commissions': request.form.get('Commissions', 0.0, type=float),  # Ensure we are getting the correct field
            'PL': request.form.get('PL', 0.0, type=float),  # Total on form maps to P/L in the database
            'setup_type': request.form.get('setup_type', ''),
            'note': request.form.get('note', ''),
            'P/L %': request.form.get('PL_percent', 0.0, type=float),  # Ensure we are getting the correct field
            'user_id': current_user.id  # Associate trade with current user
        }

        app.logger.debug(f"New trade data: {new_trade}")

        # Insert the new trade into the database
        conn = get_db_connection()
        
        # Create a DataFrame for the new trade
        new_trade_df = pd.DataFrame([new_trade])
        
        # Save only the new trade to the database
        new_trade_df.to_sql('trades', conn, if_exists='append', index=False)
        conn.close()

        app.logger.debug("New trade added successfully")
        flash('Trade added successfully!', 'success')
        return redirect(url_for('trade_log'))
    except Exception as e:
        app.logger.error(f"Error during trade add: {e}")
        flash('An error occurred while adding the trade. Please try again.', 'danger')
        return redirect(url_for('trade_log'))




@app.route('/delete_trade/<uuid:trade_id>', methods=['POST'])
@login_required
def delete_trade(trade_id):
    app.logger.debug(f"Delete trade function called with trade_id: {trade_id}")
    try:
        # Load the trade data for the current user
        conn = get_db_connection()
        
        # Delete the trade from the database by trade_id and user_id
        conn.execute("DELETE FROM trades WHERE id = ? AND user_id = ?", (str(trade_id), current_user.id))
        conn.commit()
        conn.close()
        
        app.logger.debug(f"Trade with ID {trade_id} deleted for user {current_user.id}.")
        flash('Trade deleted successfully!', 'success')
        
        return redirect(url_for('trade_log'))
    except Exception as e:
        app.logger.error(f"Error during trade delete: {e}")
        flash('An error occurred while deleting the trade. Please try again.', 'danger')
        return redirect(url_for('trade_log'))



@app.route('/bulk_delete', methods=['POST'])
@login_required
def bulk_delete():
    try:
        selected_trades = request.form.getlist('selected_trades')
        
        if not selected_trades:
            flash('No trades selected for deletion.', 'warning')
            return redirect(url_for('trade_log'))

        app.logger.debug(f"Trades selected for deletion: {selected_trades}")

        conn = get_db_connection()
        
        # Convert selected_trades to strings
        selected_trade_ids = list(map(str, selected_trades))
        
        # Create a placeholder string for the SQL query
        placeholders = ', '.join('?' for _ in selected_trade_ids)
        
        # Delete the selected trades
        query = f"DELETE FROM trades WHERE id IN ({placeholders}) AND user_id = ?"
        conn.execute(query, (*selected_trade_ids, current_user.id))
        conn.commit()
        conn.close()

        app.logger.debug("Selected trades deleted successfully")
        flash('Selected trades deleted successfully!', 'success')
        return redirect(url_for('trade_log'))
    except Exception as e:
        app.logger.error(f"Error during bulk delete: {e}")
        flash('An error occurred while deleting the trades. Please try again.', 'danger')
        return redirect(url_for('trade_log'))




@app.route('/open_trades')
@login_required
def open_trades():
    update_last_prices()  # Update last prices before fetching data
    
    conn = get_db_connection()
    open_trades_df = pd.read_sql_query("SELECT * FROM open_trades WHERE user_id = ?", conn, params=(current_user.id,))
    conn.close()

    # Ensure numeric conversion
    open_trades_df['last_price'] = open_trades_df['last_price'].astype(float)
    open_trades_df['Size'] = open_trades_df['Size'].astype(float)
    open_trades_df['Opening'] = open_trades_df['Opening'].astype(float)
    open_trades_df['Stop_Loss'] = open_trades_df['Stop_Loss'].astype(float)
    
    # Calculate total number of open trades
    total_open_trades = len(open_trades_df)
    
    # Calculate total exposure
    total_exposure = (open_trades_df['Size'] * open_trades_df['last_price']).sum()
    
    # Calculate current P/L
    total_current_pl = ((open_trades_df['last_price'] - open_trades_df['Opening']) * open_trades_df['Size']).sum()
    
    # Calculate total $ at risk
    total_at_risk = ((open_trades_df['Opening'] - open_trades_df['Stop_Loss']) * open_trades_df['Size']).sum()
    
    open_trades_dict = open_trades_df.to_dict(orient='records')
    
    return render_template('open_trades.html', 
                           open_trades=open_trades_dict,
                           total_open_trades=total_open_trades,
                           total_exposure=total_exposure,
                           total_current_pl=total_current_pl,
                           total_at_risk=total_at_risk)

@app.route('/add_open_trade', methods=['POST'])
@login_required
def add_open_trade():
    if request.method == 'POST':
        try:
            opening_price = float(request.form.get('Opening', 0.0))
            stop_loss = float(request.form.get('Stop_Loss', 0.0))
            symbol = request.form.get('Market', '').strip()

            potential_loss_percentage = 0.0
            if opening_price != 0:
                potential_loss_percentage = ((stop_loss - opening_price) / opening_price) * 100

            opened_date = request.form.get('opened-date', '')
            opened_time = request.form.get('opened-time', '')

            # Combine date and time
            def parse_and_format_datetime(date_str, time_str):
                # If time is empty, set it to '00:00:00'
                if not time_str:
                    time_str = '00:00:00'
                combined_str = f"{date_str} {time_str}"
                app.logger.debug(f"Combined date and time string: {combined_str}")
                date_formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]
                for fmt in date_formats:
                    try:
                        parsed_date = datetime.strptime(combined_str, fmt)
                        return parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError as ve:
                        app.logger.debug(f"ValueError for format {fmt}: {ve}")
                        continue
                app.logger.error(f"Failed to parse date and time: {combined_str}")
                return None

            opened_date_str = parse_and_format_datetime(opened_date, opened_time)
            if not opened_date_str:
                raise ValueError(f"Invalid opened date and time: {opened_date} {opened_time}")

            # Fetch the latest price using Alpha Vantage
            api_key = 'QJ85FALN2NTD1GUX'
            last_price = get_latest_stock_price(symbol, api_key)

            new_open_trade = {
                'id': str(uuid.uuid4()),  # Generate a new UUID for the trade
                'Opening_Ref': request.form.get('Opening_Ref', '').strip(),
                'Opened': opened_date_str,
                'Market': symbol,
                'Period': request.form.get('Period', '').strip(),
                'Direction': request.form.get('Direction', '').strip(),
                'Size': request.form.get('Size', 0.0, type=float),
                'Opening': opening_price,
                'Stop_Loss': stop_loss,
                'Trade_Ccy': request.form.get('Trade_Ccy', '').strip(),
                'Funding': request.form.get('Funding', 0.0, type=float),
                'Borrowing': request.form.get('Borrowing', 0.0, type=float),
                'Dividends': request.form.get('Dividends', 0.0, type=float),
                'LR_Prem': request.form.get('LR_Prem', 0.0, type=float),
                'Others': request.form.get('Others', 0.0, type=float),
                'Comm_Ccy': request.form.get('Comm_Ccy', '').strip(),
                'Commissions': request.form.get('Commissions', 0.0, type=float),
                'setup_type': request.form.get('setup_type', '').strip(),
                'note': request.form.get('note', '').strip(),
                'potential_loss_percentage': potential_loss_percentage,
                'last_price': last_price,
                'user_id': current_user.id  # Associate open trade with current user
            }

            new_open_trade_df = pd.DataFrame([new_open_trade])

            # Insert the new trade into the database without affecting existing trades
            conn = get_db_connection()
            new_open_trade_df.to_sql('open_trades', conn, if_exists='append', index=False)
            conn.close()

            flash('Open trade added successfully!', 'success')
            return redirect(url_for('open_trades'))
        except Exception as e:
            app.logger.error(f"Error during adding open trade: {e}")
            flash('An error occurred while adding the open trade. Please try again.', 'danger')
            return redirect(url_for('open_trades'))




@app.route('/delete_open_trade/<uuid:trade_id>', methods=['POST'])
@login_required
def delete_open_trade(trade_id):
    app.logger.debug(f"Delete open trade function called with trade_id: {trade_id}")
    try:
        # Delete the open trade from the database by trade_id and user_id
        conn = get_db_connection()
        conn.execute("DELETE FROM open_trades WHERE id = ? AND user_id = ?", (str(trade_id), current_user.id))
        conn.commit()
        conn.close()
        
        app.logger.debug(f"Open trade with ID {trade_id} deleted for user {current_user.id}.")
        flash('Open trade deleted successfully!', 'success')
        return redirect(url_for('open_trades'))
    except Exception as e:
        app.logger.error(f"Error during open trade delete: {e}")
        flash('An error occurred while deleting the open trade. Please try again.', 'danger')
        return redirect(url_for('open_trades'))

@app.route('/bulk_delete_open_trades', methods=['POST'])
@login_required
def bulk_delete_open_trades():
    try:
        selected_trades = request.form.getlist('selected_trades[]')
        
        if not selected_trades:
            return jsonify({"status": "error", "message": "No trades selected for deletion."})

        app.logger.debug(f"Open trades selected for deletion: {selected_trades}")

        conn = get_db_connection()
        # Convert selected_trades to strings
        selected_trade_ids = list(map(str, selected_trades))
        # Create a placeholder string for the SQL query
        placeholders = ', '.join('?' for _ in selected_trade_ids)
        # Delete the selected trades
        query = f"DELETE FROM open_trades WHERE id IN ({placeholders}) AND user_id = ?"
        conn.execute(query, (*selected_trade_ids, current_user.id))
        conn.commit()
        conn.close()

        app.logger.debug("Selected open trades deleted successfully")
        return jsonify({"status": "success", "message": "Selected open trades deleted successfully!"})
    except Exception as e:
        app.logger.error(f"Error during bulk delete of open trades: {e}")
        return jsonify({"status": "error", "message": "An error occurred while deleting the open trades. Please try again."})

@app.route('/save_open_trade_log', methods=['POST'])
@login_required
def save_open_trade_log():
    try:
        trade_id = request.form.get('trade_id')
        conn = get_db_connection()
        open_trades_df = pd.read_sql_query("SELECT * FROM open_trades WHERE id = ? AND user_id = ?", conn, params=(trade_id, current_user.id))

        if open_trades_df.empty:
            raise ValueError("Invalid trade ID")

        # Update only the specific fields
        if 'setup_type' in request.form:
            open_trades_df.at[0, 'setup_type'] = request.form['setup_type']
        if 'note' in request.form:
            open_trades_df.at[0, 'note'] = request.form['note']

        # Save changes back to the database
        open_trades_df.to_sql('open_trades', conn, if_exists='replace', index=False)
        conn.close()

        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f"Error during save open trade log: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/close_trade', methods=['POST'])
@login_required
def close_trade():
    if request.method == 'POST':
        try:
            # Retrieve form data
            trade_id = request.form.get('trade_id')
            closing_price = float(request.form.get('closing-price', 0.0))
            closed_date = request.form.get('closed-date', '')
            closed_time = request.form.get('closed-time', '')
            trade_commissions = float(request.form.get('commissions', 0.0))
            
            # Ensure commissions are negative
            if trade_commissions > 0:
                trade_commissions = -trade_commissions


            # Combine date and time
            def parse_and_format_datetime(date_str, time_str):
                # If time is empty, set it to '00:00:00'
                if not time_str:
                    time_str = '00:00:00'
                combined_str = f"{date_str} {time_str}"
                date_formats = ["%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y", "%Y-%m-%d"]
                for fmt in date_formats:
                    try:
                        parsed_date = datetime.strptime(combined_str, fmt)
                        return parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue
                return None

            closed_date_str = parse_and_format_datetime(closed_date, closed_time)

            app.logger.debug(f"Trade ID: {trade_id}, Closing Price: {closing_price}, Closed Date: {closed_date_str}")

            # Database connection
            conn = get_db_connection()
            open_trades_query = "SELECT * FROM open_trades WHERE id = ? AND user_id = ?"
            open_trades_df = pd.read_sql_query(open_trades_query, conn, params=(trade_id, current_user.id))
            
            if open_trades_df.empty:
                app.logger.error("Invalid trade ID or trade does not exist.")
                raise ValueError("Invalid trade ID or trade does not exist.")

            trade = open_trades_df.iloc[0].to_dict()

            # Ensure 'Opening' and 'Size' are floats
            opening_price = float(trade['Opening'])
            trade_size = float(trade['Size'])

            # Calculate P/L
            pl = (closing_price - opening_price) * trade_size
            total = pl - abs(trade_commissions)
            pl_percent = ((closing_price - opening_price) / opening_price) * 100

            new_closed_trade = {
                'id': str(uuid.uuid4()),
                'Closing_Ref': f"{trade['Market']}-{trade['Opened']}",
                'Closed': closed_date_str,
                'Opening_Ref': trade['Opening_Ref'],
                'Opened': trade['Opened'],
                'Market': trade['Market'],
                'Period': trade['Period'],
                'Direction': trade['Direction'],
                'Size': trade_size,
                'Opening': opening_price,
                'Closing': closing_price,
                'Trade_Ccy': trade['Trade_Ccy'],
                'Total': total,
                'Funding': trade['Funding'],
                'Borrowing': trade['Borrowing'],
                'Dividends': trade['Dividends'],
                'LR_Prem': trade['LR_Prem'],
                'Others': trade['Others'],
                'Comm_Ccy': trade['Comm_Ccy'],
                'Comm': trade_commissions,
                'PL': pl,
                'setup_type': trade['setup_type'],
                'note': trade['note'],
                'P/L %': pl_percent,
                'user_id': current_user.id
            }

            app.logger.debug(f"New closed trade data: {new_closed_trade}")

            # Insert the closed trade into the trades table
            new_closed_trade_df = pd.DataFrame([new_closed_trade])
            new_closed_trade_df.to_sql('trades', conn, if_exists='append', index=False)

            # Remove the closed trade from the open trades table
            open_trades_df = open_trades_df.drop(open_trades_df.index[0]).reset_index(drop=True)
            open_trades_df.to_sql('open_trades', conn, if_exists='replace', index=False)

            conn.close()

            flash('Trade closed successfully!', 'success')
            return redirect(url_for('open_trades'))
        except Exception as e:
            app.logger.error(f"Error during closing trade: {e}")
            flash('An error occurred while closing the trade. Please try again.', 'danger')
            return redirect(url_for('open_trades'))



@app.route('/get_journal/<uuid:id>', methods=['GET'])
@login_required
def get_journal(id):
    conn = get_db_connection()
    journal = conn.execute('SELECT * FROM journals WHERE id = ? AND user_id = ?', (str(id), current_user.id)).fetchone()
    conn.close()
    if journal:
        journal_dict = dict(journal)
        journal_dict['data'] = json.loads(journal_dict['data'])  # Ensure data is valid JSON
        app.logger.debug(f"Journal fetched: {journal_dict}")  # Add logging
        return jsonify(journal_dict)
    else:
        app.logger.debug("Journal not found")  # Add logging
        return jsonify({"error": "Journal not found"}), 404



@app.route('/get_journals', methods=['GET'])
@login_required
def get_journals():
    conn = get_db_connection()
    journals = conn.execute('SELECT * FROM journals WHERE user_id = ?', (current_user.id,)).fetchall()
    conn.close()
    return jsonify([dict(row) for row in journals])

@app.route('/save_journal', methods=['POST'])
@login_required
def save_journal():
    data = request.json
    journal_id = data.get('id')
    week_ending = data['weekEnding']
    fields = data['fields']
    conn = get_db_connection()

    if journal_id:
        # Update existing journal entry
        conn.execute('UPDATE journals SET week_ending = ?, data = ? WHERE id = ? AND user_id = ?',
                     (week_ending, json.dumps(fields), journal_id, current_user.id))
    else:
        # Create new journal entry
        journal_id = str(uuid.uuid4())
        conn.execute('INSERT INTO journals (id, user_id, week_ending, data) VALUES (?, ?, ?, ?)',
                     (journal_id, current_user.id, week_ending, json.dumps(fields)))

    conn.commit()
    conn.close()
    return '', 204


@app.route('/custom_fields', methods=['GET', 'POST'])
@login_required
def custom_fields():
    user_id = current_user.id

    if request.method == 'POST':
        fields = request.json.get('fields', [])
        app.logger.debug(f"Received fields to save: {fields}")

        conn = get_db_connection()
        try:
            conn.execute('DELETE FROM journal_fields WHERE user_id = ?', (user_id,))
            for field in fields:
                field_id = str(uuid.uuid4())
                app.logger.debug(f"Inserting field: {field} for user_id: {user_id}")
                conn.execute('INSERT INTO journal_fields (id, user_id, field_name) VALUES (?, ?, ?)', (field_id, user_id, field))
            conn.commit()
            app.logger.debug("Fields saved successfully")
        except Exception as e:
            app.logger.error(f"Error saving custom fields: {e}")
            return jsonify({"error": "Internal Server Error"}), 500
        finally:
            conn.close()

        return jsonify({"success": "Fields saved successfully"}), 204

    conn = get_db_connection()
    try:
        fields = conn.execute('SELECT field_name FROM journal_fields WHERE user_id = ?', (user_id,)).fetchall()
        fields_list = [field[0] for field in fields]  # Access tuple element by index
        app.logger.debug(f"Fetched custom fields: {fields_list}")
    except Exception as e:
        app.logger.error(f"Error fetching custom fields: {e}")
        fields_list = []
    finally:
        conn.close()

    return jsonify(fields_list)

@app.route('/delete_journal/<uuid:id>', methods=['DELETE'])
@login_required
def delete_journal(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM journals WHERE id = ? AND user_id = ?', (str(id), current_user.id))
    conn.commit()
    conn.close()
    return '', 204


@app.route('/weekly_journal')
@login_required
def weekly_journal():
    return render_template('weekly_journal.html')

if __name__ == '__main__':
    app.run(debug=True)
