import os
import pandas as pd
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.io as pio

UPLOAD_FOLDER = 'uploads'

def save_file_path(user_id, file_name):
    user_folder = os.path.join(UPLOAD_FOLDER, str(user_id))
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)
    file_path = os.path.join(user_folder, file_name)
    return file_path

def read_last_file_path(user_id):
    user_folder = os.path.join(UPLOAD_FOLDER, str(user_id))
    file_path_file = os.path.join(user_folder, 'last_file_path.txt')
    if os.path.exists(file_path_file):
        with open(file_path_file, 'r') as f:
            return f.read().strip()
    return None

def store_last_file_path(user_id, file_path):
    user_folder = os.path.join(UPLOAD_FOLDER, str(user_id))
    file_path_file = os.path.join(user_folder, 'last_file_path.txt')
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)
    with open(file_path_file, 'w') as f:
        f.write(file_path)

def load_and_clean_data(file_path):
    with open(file_path, 'r') as file:
        first_seven_rows = [next(file) for _ in range(7)]
    
    trades_df = pd.read_csv(file_path, skiprows=7, on_bad_lines='skip')
    trades_df.columns = trades_df.columns.str.strip()

    if 'P/L' in trades_df.columns and trades_df['P/L'].dtype == object:
        trades_df['P/L'] = trades_df['P/L'].str.replace(',', '').astype(float).round(1)
    elif 'P/L' in trades_df.columns:
        trades_df['P/L'] = trades_df['P/L'].astype(float).round(1)
    else:
        trades_df['P/L'] = 0.0

    if 'Total' in trades_df.columns and trades_df['Total'].dtype == object:
        trades_df['Total'] = trades_df['Total'].str.replace(',', '').astype(float)
    elif 'Total' in trades_df.columns:
        trades_df['Total'] = trades_df['Total'].astype(float)
    else:
        trades_df['Total'] = trades_df['P/L']

    if 'Commissions' not in trades_df.columns:
        trades_df['Commissions'] = trades_df['Total'] - trades_df['P/L']
    trades_df['Commissions'] = trades_df['Commissions'].round(1)

    if 'Closing' in trades_df.columns and 'Opening' in trades_df.columns:
        trades_df['P/L %'] = ((trades_df['Closing'] - trades_df['Opening']) / trades_df['Opening']) * 100
        trades_df['P/L %'] = trades_df['P/L %'].round(2)
    else:
        trades_df['P/L %'] = 0.0

    if 'Closed' in trades_df.columns:
        try:
            trades_df['Closed'] = pd.to_datetime(trades_df['Closed'], format='%d-%m-%Y %H:%M:%S').dt.date
        except ValueError:
            trades_df['Closed'] = pd.to_datetime(trades_df['Closed'], format='%Y-%m-%d').dt.date

    if 'setup_type' not in trades_df.columns:
        trades_df['setup_type'] = ''
    trades_df['setup_type'] = trades_df['setup_type'].fillna('')

    if 'note' not in trades_df.columns:
        trades_df['note'] = ''
    trades_df['note'] = trades_df['note'].fillna('')

    return trades_df, first_seven_rows

def filter_data(trades_df, filter_type):
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
    total_commissions = round(trades_df['Commissions'].sum())
    avg_percent_gain = round(winners['P/L %'].mean(), 2) if num_winners > 0 else 0
    avg_percent_loss = round(losers['P/L %'].mean(), 2) if num_losers > 0 else 0
    gross_profit_loss = round(trades_df['P/L'].sum())
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

    trades_df['HoverText'] = trades_df.apply(lambda row: f"Market: {row['Market']}<br>P/L: ${row['P/L']}", axis=1)
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

    columns_to_display = ["Opened", "Market", "Direction", "Size", "Opening", "Closing", "P/L", "Total", "Commissions", "P/L %", "setup_type", "note"]
    trades_df_filtered = trades_df.loc[:, trades_df.columns.intersection(columns_to_display)]
    trade_log_dict = trades_df_filtered.to_dict('records')

    return equity_curve_html, daily_pl_html, overview, trade_stats, trade_log_dict
