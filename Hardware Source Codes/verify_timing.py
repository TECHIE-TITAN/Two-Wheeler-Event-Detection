#!/usr/bin/env python3
"""
Quick script to verify actual sampling frequency from CSV logs.
Usage: python3 verify_timing.py <csv_file>
"""

import sys
import csv
from datetime import datetime

def analyze_timing(csv_file):
    """Analyze timestamp intervals in a CSV file."""
    timestamps = []
    
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S.%f')
                timestamps.append(ts)
            except Exception as e:
                continue
    
    if len(timestamps) < 2:
        print("Not enough timestamps to analyze")
        return
    
    # Calculate intervals in milliseconds
    intervals = []
    for i in range(len(timestamps) - 1):
        delta_ms = (timestamps[i+1] - timestamps[i]).total_seconds() * 1000
        intervals.append(delta_ms)
    
    # Statistics
    avg_interval = sum(intervals) / len(intervals)
    min_interval = min(intervals)
    max_interval = max(intervals)
    actual_freq = 1000 / avg_interval if avg_interval > 0 else 0
    
    # Count how many are within tolerance
    target_interval = 10.0  # ms for 100 Hz
    tolerance = 2.0  # ms
    within_tolerance = sum(1 for i in intervals if abs(i - target_interval) <= tolerance)
    percentage = (within_tolerance / len(intervals)) * 100
    
    print(f"\n{'='*60}")
    print(f"Timing Analysis for: {csv_file}")
    print(f"{'='*60}")
    print(f"Total samples: {len(timestamps)}")
    print(f"Total intervals analyzed: {len(intervals)}")
    print(f"\nInterval Statistics (milliseconds):")
    print(f"  Average:  {avg_interval:.2f} ms")
    print(f"  Minimum:  {min_interval:.2f} ms")
    print(f"  Maximum:  {max_interval:.2f} ms")
    print(f"\nFrequency Analysis:")
    print(f"  Target:   100.0 Hz (10.0 ms interval)")
    print(f"  Actual:   {actual_freq:.1f} Hz ({avg_interval:.2f} ms interval)")
    print(f"  Within tolerance ({target_interval}±{tolerance}ms): {percentage:.1f}%")
    
    # Show distribution
    print(f"\nInterval Distribution:")
    buckets = {
        "< 5ms": sum(1 for i in intervals if i < 5),
        "5-8ms": sum(1 for i in intervals if 5 <= i < 8),
        "8-12ms": sum(1 for i in intervals if 8 <= i < 12),
        "12-15ms": sum(1 for i in intervals if 12 <= i < 15),
        "15-20ms": sum(1 for i in intervals if 15 <= i < 20),
        "> 20ms": sum(1 for i in intervals if i >= 20),
    }
    for label, count in buckets.items():
        pct = (count / len(intervals)) * 100
        bar = '█' * int(pct / 2)
        print(f"  {label:8} {count:5} ({pct:5.1f}%) {bar}")
    
    # Show worst offenders
    sorted_intervals = sorted(enumerate(intervals), key=lambda x: abs(x[1] - target_interval), reverse=True)
    print(f"\nWorst 5 intervals:")
    for idx, interval in sorted_intervals[:5]:
        print(f"  Sample {idx} -> {idx+1}: {interval:.2f} ms")
    
    print(f"{'='*60}\n")

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 verify_timing.py <csv_file>")
        sys.exit(1)
    
    analyze_timing(sys.argv[1])
