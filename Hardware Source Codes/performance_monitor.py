"""
Performance monitoring utility for diagnosing sampling rate issues.
Add these snippets to main2.py if you need to debug performance bottlenecks.
"""

import time
from collections import deque
import statistics

class LoopTimer:
    """Measure and report loop timing statistics."""
    
    def __init__(self, window_size=1000):
        self.times = deque(maxlen=window_size)
        self.last_time = None
        self.sample_count = 0
        
    def tick(self):
        """Record a loop iteration."""
        now = time.perf_counter()
        if self.last_time is not None:
            delta = now - self.last_time
            self.times.append(delta)
        self.last_time = now
        self.sample_count += 1
        
    def get_stats(self):
        """Get timing statistics."""
        if not self.times:
            return None
        
        times_ms = [t * 1000 for t in self.times]
        return {
            'count': len(times_ms),
            'mean_ms': statistics.mean(times_ms),
            'median_ms': statistics.median(times_ms),
            'min_ms': min(times_ms),
            'max_ms': max(times_ms),
            'stdev_ms': statistics.stdev(times_ms) if len(times_ms) > 1 else 0,
            'hz': 1000.0 / statistics.mean(times_ms) if times_ms else 0
        }
    
    def print_stats(self):
        """Print timing statistics."""
        stats = self.get_stats()
        if stats:
            print(f"\n=== Loop Performance Stats (last {stats['count']} samples) ===")
            print(f"Frequency: {stats['hz']:.2f} Hz")
            print(f"Mean:   {stats['mean_ms']:.3f} ms")
            print(f"Median: {stats['median_ms']:.3f} ms")
            print(f"Min:    {stats['min_ms']:.3f} ms")
            print(f"Max:    {stats['max_ms']:.3f} ms")
            print(f"StdDev: {stats['stdev_ms']:.3f} ms")
            print(f"Target: 10.000 ms (100 Hz)")
            print("=" * 50)


class SectionTimer:
    """Measure time spent in specific code sections."""
    
    def __init__(self):
        self.sections = {}
        self.current_section = None
        self.section_start = None
        
    def start(self, name):
        """Start timing a section."""
        if name not in self.sections:
            self.sections[name] = deque(maxlen=1000)
        self.current_section = name
        self.section_start = time.perf_counter()
        
    def end(self):
        """End timing current section."""
        if self.current_section and self.section_start:
            elapsed = time.perf_counter() - self.section_start
            self.sections[self.current_section].append(elapsed)
            self.current_section = None
            self.section_start = None
    
    def print_stats(self):
        """Print timing stats for all sections."""
        print("\n=== Section Timing Stats (ms) ===")
        total_time = 0
        section_means = []
        
        for name, times in self.sections.items():
            if times:
                times_ms = [t * 1000 for t in times]
                mean_ms = statistics.mean(times_ms)
                section_means.append((name, mean_ms))
                total_time += mean_ms
        
        # Sort by mean time (descending)
        section_means.sort(key=lambda x: x[1], reverse=True)
        
        for name, mean_ms in section_means:
            pct = (mean_ms / total_time * 100) if total_time > 0 else 0
            print(f"{name:30s}: {mean_ms:6.3f} ms ({pct:5.1f}%)")
        
        print(f"{'TOTAL':30s}: {total_time:6.3f} ms")
        print("=" * 50)


# Example usage - add to main2.py:
"""
# At the top of main():
loop_timer = LoopTimer(window_size=1000)
section_timer = SectionTimer()

# In the main loop:
while not stop_event.is_set():
    loop_timer.tick()  # Measure loop frequency
    
    section_timer.start("sleep")
    # ... sleep code ...
    section_timer.end()
    
    section_timer.start("data_lock")
    with data_lock:
        # ... lock code ...
    section_timer.end()
    
    section_timer.start("speed_calc")
    # ... speed calculation ...
    section_timer.end()
    
    section_timer.start("csv_queue")
    # ... queue operations ...
    section_timer.end()
    
    # Print stats every 1000 samples
    if loop_timer.sample_count % 1000 == 0:
        loop_timer.print_stats()
        section_timer.print_stats()
"""

if __name__ == '__main__':
    # Test the timers
    import random
    
    print("Testing performance monitoring tools...\n")
    
    loop_timer = LoopTimer(window_size=100)
    section_timer = SectionTimer()
    
    for i in range(100):
        loop_timer.tick()
        
        section_timer.start("section_a")
        time.sleep(random.uniform(0.005, 0.008))
        section_timer.end()
        
        section_timer.start("section_b")
        time.sleep(random.uniform(0.001, 0.003))
        section_timer.end()
        
        # Simulate 100 Hz target
        time.sleep(0.001)
    
    loop_timer.print_stats()
    section_timer.print_stats()
