#!/usr/bin/env python3
"""
Auto-calibration script for weather trading bot.
Calculates rolling bias corrections per city based on prediction errors.

Usage:
    python3 auto_calibrate.py --city MIA --days 30
    python3 auto_calibrate.py --all-cities --days 30
    python3 auto_calibrate.py --output recommendations.json
"""

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# Database path - will be overridden by --db flag
DEFAULT_DB_PATH = "/root/.openclaw/workspace/Drewbots/trading/weather.db"


def get_connection(db_path: str = DEFAULT_DB_PATH):
    """Connect to the weather database."""
    return sqlite3.connect(db_path)


def get_prediction_errors(conn, city: str = None, days: int = 30) -> list:
    """
    Get prediction errors from prediction_log table.
    
    Returns list of dicts with:
    - city
    - predicted_temp
    - actual_temp (from CLI settlement)
    - error = actual - predicted
    - abs_error = |error|
    - bracket
    - settlement_price
    """
    cutoff_date = datetime.now() - timedelta(days=days)
    
    if city:
        where_clause = f"WHERE city = '{city}' AND timestamp > '{cutoff_date.isoformat()}'"
    else:
        where_clause = f"WHERE timestamp > '{cutoff_date.isoformat()}'"
    
    query = f"""
    SELECT 
        city,
        predicted_high,
        predicted_low,
        actual_high,
        actual_low,
        bracket,
        settlement_price,
        entry_price,
        profit_loss
    FROM prediction_log
    {where_clause}
    ORDER BY timestamp DESC
    """
    
    try:
        cursor = conn.execute(query)
        columns = [desc[0] for desc in cursor.description]
        results = []
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            
            # Calculate errors for high and low predictions
            if record.get('predicted_high') and record.get('actual_high'):
                record['high_error'] = record['actual_high'] - record['predicted_high']
                record['high_abs_error'] = abs(record['high_error'])
            if record.get('predicted_low') and record.get('actual_low'):
                record['low_error'] = record['actual_low'] - record['predicted_low']
                record['low_abs_error'] = abs(record['low_error'])
            
            results.append(record)
        return results
    
    except sqlite3.OperationalError as e:
        print(f"Error querying prediction_log: {e}")
        print("Table may not exist or schema different. Available tables:")
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        for row in cursor.fetchall():
            print(f"  - {row[0]}")
        return []


def calculate_city_bias(errors: list, city: str) -> dict:
    """Calculate bias and recommended adjustments for a city."""
    
    high_errors = [e['high_error'] for e in errors if 'high_error' in e and e['high_error'] is not None]
    low_errors = [e['low_error'] for e in errors if 'low_error' in e and e['low_error'] is not None]
    
    result = {
        'city': city,
        'sample_size': len(errors),
        'high_bias': {
            'current': 0,  # Would pull from signal_generator.py
            'recommended': sum(high_errors) / len(high_errors) if high_errors else 0,
            'count': len(high_errors),
            'std_dev': (sum((e - sum(high_errors)/len(high_errors))**2 for e in high_errors) / len(high_errors))**0.5 if len(high_errors) > 1 else 0,
        },
        'low_bias': {
            'current': 0,
            'recommended': sum(low_errors) / len(low_errors) if low_errors else 0,
            'count': len(low_errors),
            'std_dev': (sum((e - sum(low_errors)/len(low_errors))**2 for e in low_errors) / len(low_errors))**0.5 if len(low_errors) > 1 else 0,
        }
    }
    
    return result


def calculate_optimal_std_dev(errors: list) -> dict:
    """Calculate optimal standard deviation based on prediction accuracy."""
    
    all_errors = []
    for e in errors:
        if 'high_error' in e and e['high_error'] is not None:
            all_errors.append(e['high_error'])
        if 'low_error' in e and e['low_error'] is not None:
            all_errors.append(e['low_error'])
    
    if not all_errors:
        return {'recommended': 4.0, 'count': 0}
    
    # Use 1.5x standard deviation as the floor for safety
    std = (sum((e - sum(all_errors)/len(all_errors))**2 for e in all_errors) / len(all_errors))**0.5
    recommended_std = max(2.5, min(6.0, std * 1.5))  # Clamp between 2.5 and 6.0
    
    return {
        'recommended': round(recommended_std, 1),
        'actual_std': round(std, 2),
        'count': len(all_errors)
    }


def generate_code_recommendations(bias_analysis: dict, std_analysis: dict) -> str:
    """Generate code changes to apply the recommended parameters."""
    
    lines = [
        "# Recommended parameter updates for signal_generator.py",
        "",
        "# HIGH_BIASES updates:",
        "HIGH_BIASES = {",
    ]
    
    for city, data in bias_analysis.items():
        if data['high_bias']['count'] > 0:
            recommended = round(data['high_bias']['recommended'], 1)
            lines.append(f'    "{city}": {recommended},  # was X.X, from {data["high_bias"]["count"]} samples')
    
    lines.extend([
        "}",
        "",
        "# LOW_BIASES updates:",
        "LOW_BIASES = {",
    ])
    
    for city, data in bias_analysis.items():
        if data['low_bias']['count'] > 0:
            recommended = round(data['low_bias']['recommended'], 1)
            lines.extend([
        f'    "{city}": {recommended},  # was Y.Y, from {data["low_bias"]["count"]} samples'
            ])
    
    lines.extend([
        "}",
        "",
        f"# CITY_STD_FLOOR updates:",
        f"CITY_STD_FLOOR = {{",
    ])
    
    for city, data in bias_analysis.items():
        std = std_analysis.get(city, {}).get('recommended', 4.0)
        lines.append(f'    "{city}": {std},')
    
    lines.append("}")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Auto-calibrate trading parameters")
    parser.add_argument('--db', default=DEFAULT_DB_PATH, help='Path to weather.db')
    parser.add_argument('--city', help='Specific city to analyze (default: all)')
    parser.add_argument('--days', type=int, default=30, help='Days of history to analyze')
    parser.add_argument('--output', help='Output JSON file for results')
    parser.add_argument('--show-code', action='store_true', help='Show code recommendations')
    
    args = parser.parse_args()
    
    try:
        conn = get_connection(args.db)
    except Exception as e:
        print(f"Cannot connect to database: {e}")
        print("NOTE: This script requires access to the weather.db on DrewOps' server.")
        print("Use the DB API: http://170.187.200.139:8777")
        return
    
    print(f"Analyzing prediction errors for last {args.days} days...")
    
    if args.city:
        cities = [args.city]
    else:
        # Get all cities from prediction_log
        cursor = conn.execute("SELECT DISTINCT city FROM prediction_log")
        cities = [row[0] for row in cursor.fetchall()]
    
    results = {}
    
    for city in cities:
        print(f"\n=== {city} ===")
        errors = get_prediction_errors(conn, city, args.days)
        
        if not errors:
            print(f"  No data for {city}")
            continue
        
        bias_analysis = calculate_city_bias(errors, city)
        std_analysis = calculate_optimal_std_dev(errors)
        
        print(f"  Sample size: {len(errors)}")
        print(f"  High bias: current X.X -> recommended {bias_analysis['high_bias']['recommended']:.1f}°F (from {bias_analysis['high_bias']['count']} samples)")
        print(f"  Low bias: current Y.Y -> recommended {bias_analysis['low_bias']['recommended']:.1f}°F (from {bias_analysis['low_bias']['count']} samples)")
        print(f"  Std dev: recommended {std_analysis['recommended']}°F")
        
        results[city] = {
            'bias': bias_analysis,
            'std_dev': std_analysis,
            'sample_size': len(errors)
        }
    
    if args.show_code:
        print("\n" + "="*50)
        print("RECOMMENDED CODE CHANGES:")
        print("="*50)
        print(generate_code_recommendations(results, {}))
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults written to {args.output}")
    
    conn.close()


if __name__ == "__main__":
    main()
