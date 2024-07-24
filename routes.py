from flask import render_template, request, redirect, url_for, flash, jsonify
from app import app, db, bcrypt
from forms import RegistrationForm, LoginForm
from models import User
from flask_login import login_user, logout_user, login_required, current_user
import os
import pandas as pd
from utils import *

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/journal')
@login_required
def journal():
    file_path = read_last_file_path(current_user.id)
    if not file_path or not os.path.exists(file_path):
        return render_template('journal.html', overview={}, trade_stats={}, equity_curve="<p>No data available. Please upload a CSV file.</p>", daily_pl="", calendar_data="", trade_log="", filter_type="", message="")

    trades_df, first_seven_rows = load_and_clean_data(file_path)
    filter_type = request.args.get('filter', 'all')
    filtered_trades_df = filter_data(trades_df, filter_type)

    if filtered_trades_df.empty:
        message = f"No trades available for {filter_type.replace('_', ' ').title()} setup"
        return render_template('journal.html', equity_curve="", daily_pl="", calendar_data="", overview={}, trade_stats={}, trade_log=[], filter_type=filter_type, message=message)

    analysis_results = perform_analysis(filtered_trades_df)
    equity_curve_html, daily_pl_html, overview, trade_stats, trade_log_dict = create_dashboard(*analysis_results, filtered_trades_df)
    return render_template('journal.html', equity_curve=equity_curve_html, daily_pl=daily_pl_html, calendar_data="", overview=overview, trade_stats=trade_stats, trade_log=trade_log_dict, filter_type=filter_type, message="")

@app.route('/trade_log')
@login_required
def trade_log():
    file_path = read_last_file_path(current_user.id)
    if not file_path or not os.path.exists(file_path):
        return render_template('trade_log.html', trade_log=[])

    trades_df, first_seven_rows = load_and_clean_data(file_path)
    trade_log_dict = trades_df.to_dict(orient='records')
    return render_template('trade_log.html', trade_log=trade_log_dict)


@app.route('/calendar')
@login_required
def calendar():
    return render_template('calendar.html')

@app.route('/overview')
@login_required
def overview_trade_statistics():
    file_path = read_last_file_path(current_user.id)
    if not file_path or not os.path.exists(file_path):
        return render_template('overview_trade_statistics.html', overview={}, trade_stats={}, filter_type="", message="No data available. Please upload a CSV file.")

    trades_df, first_seven_rows = load_and_clean_data(file_path)
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
    file_path = read_last_file_path(current_user.id)
    if not file_path or not os.path.exists(file_path):
        return render_template('equity_curve.html', equity_curve="<p>No data available. Please upload a CSV file.</p>", daily_pl="", filter_type="", message="")

    trades_df, first_seven_rows = load_and_clean_data(file_path)
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
        user = User.query.filter_by(username=form.username.data).first()
        if user:
            flash('That username is taken. Please choose a different one.', 'danger')
        else:
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
        if user:
            if bcrypt.check_password_hash(user.password, form.password.data):
                login_user(user, remember=form.remember.data)
                return redirect(url_for('journal'))
            else:
                flash('Incorrect password. Please try again.', 'danger')
        else:
            flash('Email does not exist. Please register first.', 'danger')
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
                trades_df, first_seven_rows = load_and_clean_data(file_path)
                filter_type = 'all'
                filtered_trades_df = filter_data(trades_df, filter_type)
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
        file_path = read_last_file_path(current_user.id)
        if 'file' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        if file:
            new_file_path = save_file_path(current_user.id, file.filename)
            file.save(new_file_path)

            # Load existing and new data
            existing_trades_df, first_seven_rows = load_and_clean_data(file_path)
            new_trades_df, _ = load_and_clean_data(new_file_path)

            # Merge new trades with existing trades, avoiding duplicates based on both 'closing Ref' and 'opening ref'
            combined_trades_df = pd.concat([existing_trades_df, new_trades_df]).drop_duplicates(subset=['Closing Ref', 'Opening Ref'], keep='first')

            # Convert DataFrame back to CSV format
            combined_csv_data = combined_trades_df.to_csv(index=False, lineterminator='\n')

            # Combine first seven rows and the CSV data
            combined_csv_data = ''.join(first_seven_rows) + combined_csv_data

            # Save the combined data back to the existing file path
            with open(file_path, 'w', newline='') as file:
                file.write(combined_csv_data)

            store_last_file_path(current_user.id, file_path)

            filter_type = 'all'
            filtered_trades_df = filter_data(combined_trades_df, filter_type)
            analysis_results = perform_analysis(filtered_trades_df)
            equity_curve_html, daily_pl_html, overview, trade_stats, trade_log_dict = create_dashboard(*analysis_results, filtered_trades_df)
            return render_template('journal.html', equity_curve=equity_curve_html, daily_pl=daily_pl_html, calendar_data="", overview=overview, trade_stats=trade_stats, trade_log=trade_log_dict, filter_type=filter_type)
    except Exception as e:
        flash('An error occurred while processing the file. Please ensure the data is correctly formatted and try again.', 'danger')
        app.logger.error(f"Error during file merge: {e}")
        return redirect(url_for('journal'))


@app.route('/save_trade_log', methods=['POST'])
@login_required
def save_trade_log():
    file_path = read_last_file_path(current_user.id)
    trades_df, first_seven_rows = load_and_clean_data(file_path)

    for index, row in trades_df.iterrows():
        trades_df.loc[index, 'setup_type'] = request.form.get(f'setup_type_{index+1}', '')
        trades_df.loc[index, 'note'] = request.form.get(f'note_{index+1}', '')

    trades_df['note'] = trades_df['note'].fillna('')
    trades_df['setup_type'] = trades_df['setup_type'].fillna('')

    columns_order = ['Closing Ref', 'Closed', 'Opening Ref', 'Opened', 'Market', 'Period', 'Direction', 'Size',
                     'Opening', 'Closing', 'Trade Ccy.', 'P/L', 'Funding', 'Borrowing', 'Dividends', 'LR Prem.',
                     'Others', 'Comm. Ccy.', 'Comm.', 'Total', 'Commissions', 'P/L %', 'setup_type', 'note']
    trades_df = trades_df.reindex(columns=columns_order, fill_value='')

    csv_data = trades_df.to_csv(index=False, lineterminator='\n')

    combined_csv_data = ''.join(first_seven_rows) + csv_data

    with open(file_path, 'w', newline='') as file:
        file.write(combined_csv_data)
    
    reloaded_df, _ = load_and_clean_data(file_path)

    reloaded_df['note'] = reloaded_df['note'].fillna('')
    reloaded_df['setup_type'] = reloaded_df['setup_type'].fillna('')

    filter_type = request.args.get('filter', 'all')
    filtered_trades_df = filter_data(reloaded_df, filter_type)
    analysis_results = perform_analysis(filtered_trades_df)
    equity_curve_html, daily_pl_html, overview, trade_stats, trade_log_dict = create_dashboard(*analysis_results, filtered_trades_df)
    return render_template('journal.html', equity_curve=equity_curve_html, daily_pl=daily_pl_html, calendar_data="", overview=overview, trade_stats=trade_stats, trade_log=trade_log_dict, filter_type=filter_type)

@app.route('/calendar_data')
@login_required
def calendar_data():
    file_path = read_last_file_path(current_user.id)
    if not file_path or not os.path.exists(file_path):
        return jsonify([])

    trades_df, _ = load_and_clean_data(file_path)
    daily_pl = trades_df.groupby('Closed')['Total'].sum().reset_index()
    daily_pl['Closed'] = pd.to_datetime(daily_pl['Closed'])

    daily_pl['Week'] = daily_pl['Closed'].dt.to_period('W').apply(lambda r: r.start_time)
    weekly_totals = daily_pl.groupby('Week')['Total'].sum().reset_index()

    daily_pl['Closed'] = daily_pl['Closed'].astype(str)
    weekly_totals['Week'] = pd.to_datetime(weekly_totals['Week'])
    weekly_totals['Saturday'] = weekly_totals['Week'] + pd.DateOffset(days=5)

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

    return jsonify(events)
