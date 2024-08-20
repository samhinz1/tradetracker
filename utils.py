import os
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.io as pio

UPLOAD_FOLDER = 'uploads'
DB_FILE_PATH = 'instance/site.db'

def save_file_path(user_id, file_name):
    user_folder = os.path.join(UPLOAD_FOLDER, str(user_id))
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)
    file_path = os.path.join(user_folder, file_name)
    return file_path

def read_last_file_path(user_id):
    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT file_path FROM file_paths WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0]
    return None

def store_last_file_path(user_id, file_path):
    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO file_paths (user_id, file_path) 
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET file_path=excluded.file_path;
    ''', (user_id, file_path))
    conn.commit()
    conn.close()

def load_and_clean_data(file_path):
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

    trades_df['PL'] = trades_df['PL'].str.replace(',', '').astype(float).round(1)
    trades_df['Total'] = trades_df['Total'].str.replace(',', '').astype(float)
    trades_df['Comm'] = trades_df['Total'] - trades_df['PL']
    trades_df['Comm'] = trades_df['Comm'].round(1)

    trades_df['P/L %'] = ((trades_df['Closing'] - trades_df['Opening']) / trades_df['Opening']) * 100
    trades_df['P/L %'] = trades_df['P/L %'].round(2)

    # Convert 'Closed' column to datetime and handle errors
    trades_df['Closed'] = pd.to_datetime(trades_df['Closed'], dayfirst=True, errors='coerce')
    
    # Drop rows where 'Closed' could not be converted to a date
    trades_df = trades_df.dropna(subset=['Closed'])

    # Convert to date only (no time component)
    trades_df['Closed'] = trades_df['Closed'].dt.date

    if 'setup_type' not in trades_df.columns:
        trades_df['setup_type'] = ''
    trades_df['setup_type'] = trades_df['setup_type'].fillna('')
    if 'note' not in trades_df.columns:
        trades_df['note'] = ''
    trades_df['note'] = trades_df['note'].fillna('')

    return trades_df


def load_and_clean_data_from_sqlite():
    conn = sqlite3.connect(DB_FILE_PATH)
    trades_df = pd.read_sql_query("SELECT * FROM trades", conn)
    conn.close()

    trades_df.columns = trades_df.columns.str.strip()
    trades_df['PL'] = trades_df['PL'].astype(float).round(1)
    trades_df['Total'] = trades_df['Total'].astype(float)

    if 'Commissions' not in trades_df.columns:
        trades_df['Commissions'] = trades_df['Total'] - trades_df['PL']
    trades_df['Commissions'] = trades_df['Commissions'].round(1)
        
    # Convert 'Closed' column to datetime and handle errors
    trades_df['Closed'] = pd.to_datetime(trades_df['Closed'], dayfirst=True, errors='coerce')
    
    # Drop rows where 'Closed' could not be converted to a date
    trades_df = trades_df.dropna(subset=['Closed'])

    # Convert to date only (no time component)
    trades_df['Closed'] = trades_df['Closed'].dt.date

    if 'setup_type' not in trades_df.columns:
        trades_df['setup_type'] = ''
    trades_df['setup_type'] = trades_df['setup_type'].fillna('')

    if 'note' not in trades_df.columns:
        trades_df['note'] = ''
    trades_df['note'] = trades_df['note'].fillna('')

    return trades_df


def filter_data(trades_df, filter_type):
    # Ensure 'Closed' column is in datetime.date format
    trades_df['Closed'] = pd.to_datetime(trades_df['Closed'], errors='coerce').dt.date

    today = datetime.today().date()
    if filter_type == 'prior_week':
        start_date = today - timedelta(days=today.weekday() + 7)
        end_date = start_date + timedelta(days=4)
        filtered_df = trades_df[(trades_df['Closed'] >= start_date) & (trades_df['Closed'] <= end_date)]
    elif filter_type == 'prior_7_days':
        start_date = today - timedelta(days=7)
        filtered_df = trades_df[trades_df['Closed'] >= start_date]
    elif filter_type == 'prior_month':
        start_date = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        end_date = today.replace(day=1) - timedelta(days=1)
        filtered_df = trades_df[(trades_df['Closed'] >= start_date) & (trades_df['Closed'] <= end_date)]
    elif filter_type == 'year_to_date':
        start_date = today.replace(month=1, day=1)
        filtered_df = trades_df[trades_df['Closed'] >= start_date]
    elif filter_type in ['breakout_with_pivot', 'dtp', 'pullback_buy', 'pullback_buy_to_base', 'powerbase', 'century_play', 'other']:
        setup_type_mapping = {
            'breakout_with_pivot': 'Breakout with Pivot',
            'dtp': 'DTP',
            'pullback_buy': 'Pullback Buy',
            'pullback_buy_to_base': 'Pullback Buy to base',
            'powerbase': 'Powerbase',
            'century_play': 'Century Play',
            'other': 'Other'
        }
        filtered_df = trades_df[trades_df['setup_type'] == setup_type_mapping[filter_type]]
    else:
        filtered_df = trades_df
    return filtered_df


def perform_analysis(trades_df):
    trades_df['Closing'] = pd.to_numeric(trades_df['Closing'], errors='coerce')
    trades_df['Opening'] = pd.to_numeric(trades_df['Opening'], errors='coerce')
    trades_df['Total'] = pd.to_numeric(trades_df['Total'], errors='coerce')
    trades_df['Commissions'] = pd.to_numeric(trades_df.get('Commissions', 0), errors='coerce')
    trades_df['Comm'] = pd.to_numeric(trades_df.get('Comm', 0), errors='coerce')
    trades_df['PL'] = pd.to_numeric(trades_df['PL'], errors='coerce')

    trades_df['P/L %'] = ((trades_df['Closing'] - trades_df['Opening']) / trades_df['Opening']) * 100
    trades_df['P/L %'] = trades_df['P/L %'].round(2)

    winners = trades_df[trades_df['Total'] > 0]
    losers = trades_df[trades_df['Total'] <= 0]
    num_winners = len(winners)
    num_losers = len(losers)
    total_trades = len(trades_df)
    win_loss_ratio = num_winners / num_losers if num_losers != 0 else float('inf')
    avg_win = round(winners['Total'].mean()) if num_winners > 0 else 0
    avg_loss = round(losers['Total'].mean()) if num_losers > 0 else 0
    win_rate = num_winners / len(trades_df)
    loss_rate = num_losers / len(trades_df)
    expectancy = round(abs((win_rate * avg_win) / (loss_rate * avg_loss)) if loss_rate != 0 else float('inf'), 2)
    daily_pl = trades_df.groupby('Closed')['Total'].sum().reset_index()
    daily_pl['Cumulative P/L'] = daily_pl['Total'].cumsum()

    # Check for 'Comm' or 'Commissions' column and sum the values
    total_commissions = round(trades_df['Comm'].sum() + trades_df['Commissions'].sum()) + trades_df['Funding'].sum() 

    avg_percent_gain = round(winners['P/L %'].mean(), 2) if num_winners > 0 else 0
    avg_percent_loss = round(losers['P/L %'].mean(), 2) if num_losers > 0 else 0
    gross_profit_loss = round(trades_df['PL'].sum())
    net_profit = gross_profit_loss - abs(total_commissions)

    return (num_winners, num_losers, total_trades, win_loss_ratio, expectancy, daily_pl, total_commissions, avg_win,
            avg_loss, avg_percent_gain, avg_percent_loss, gross_profit_loss, net_profit)

def create_dashboard(num_winners, num_losers, total_trades, win_loss_ratio, expectancy, daily_pl, total_commissions,
                     avg_win, avg_loss, avg_percent_gain, avg_percent_loss, gross_profit_loss, net_profit, trades_df):

    equity_curve_fig = go.Figure()

    equity_curve_fig.add_trace(go.Scatter(
        x=daily_pl['Closed'],
        y=daily_pl['Cumulative P/L'],
        mode='lines',
        name='Equity Curve',
        line=dict(color='rgb(46, 255, 171)')
    ))

    equity_curve_fig.update_layout(
        title="Equity Curve",
        xaxis_title="Date",
        yaxis_title="Cumulative P/L",
        template="plotly_dark",
        plot_bgcolor='rgb(31, 41, 50)',
        paper_bgcolor='rgb(31, 41, 50)',
        font=dict(color='rgb(206, 215, 224)'),
        dragmode='pan',
        yaxis=dict(
            tickprefix='$',
        ),
    )

    equity_curve_html = pio.to_html(equity_curve_fig, full_html=False)

    trades_df['HoverText'] = trades_df.apply(lambda row: f"Market: {row['Market']}<br>P/L: ${row['PL']}", axis=1)
    hover_texts = trades_df.groupby('Closed')['HoverText'].apply(lambda x: '<br><br>'.join(x) if len(x) <= 10 else '<br><br>'.join(x[:2]) + '<br><br>...and more trades').reset_index()
    
    daily_pl = pd.merge(daily_pl, hover_texts, on='Closed', how='left')
    daily_pl['HoverText'] = daily_pl.apply(lambda row: f"Total P/L: ${row['Total']}<br><br>{row['HoverText']}", axis=1)

    daily_pl_fig = go.Figure()

    daily_pl_fig.add_trace(go.Bar(
        x=daily_pl['Closed'],
        y=daily_pl['Total'],
        hovertext=daily_pl['HoverText'],
        hoverinfo='text',
        marker_color=daily_pl['Total'].apply(lambda x: 'rgb(46, 255, 171)' if x >= 0 else 'rgb(255, 46, 46)'),
        name='Daily P/L'
    ))

    daily_pl_fig.update_layout(
        title="Daily total return",
        xaxis_title="Date",
        yaxis_title="Net P/L",
        template="plotly_dark",
        plot_bgcolor='rgb(31, 41, 50)',
        paper_bgcolor='rgb(31, 41, 50)',
        font=dict(color='rgb(206, 215, 224)'),
    )

    daily_pl_html = pio.to_html(daily_pl_fig, full_html=False)

    overview = {
        "Gross Profit/Loss": f"${gross_profit_loss}",
        "Total Commissions": f"${total_commissions}",
        "Net Profit/Loss": f"${net_profit}"
    }

    trade_stats = {
        "Number of Winners": num_winners,
        "Number of Losers": num_losers,
        "Total Trades": total_trades,
        "Win/Loss Ratio": win_loss_ratio,
        "Expectancy": expectancy,
        "Average Win": f"${avg_win}",
        "Average Loss": f"${avg_loss}",
        "Average % Gain": f"{avg_percent_gain}%",
        "Average % Loss": f"{avg_percent_loss}%"
    }

    columns_to_display = ["Opened", "Market", "Direction", "Size", "Opening", "Closing", "PL", "Total", "Commissions", "P/L %", "setup_type", "note"]
    trades_df_filtered = trades_df.loc[:, trades_df.columns.intersection(columns_to_display)]
    trade_log_dict = trades_df_filtered.to_dict('records')

    return equity_curve_html, daily_pl_html, overview, trade_stats, trade_log_dict
