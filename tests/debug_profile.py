
import asyncio
import os
import sys
import time
import psutil
import logging

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("DebugProfile")

# Add project root to path to import core modules
sys.path.append(os.getcwd())

from core.gemini_automation import GeminiAutomation

def get_process_count(process_name="chrome"):
    """Count number of processes matching the name."""
    count = 0
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            # Check name or cmdline for chromium/chrome
            if process_name in proc.info['name'].lower() or \
               (proc.info['cmdline'] and any(process_name in arg.lower() for arg in proc.info['cmdline'])):
                count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return count

def get_memory_usage():
    """Get current memory usage of the python process + children."""
    process = psutil.Process(os.getpid())
    mem = process.memory_info().rss / 1024 / 1024  # MB
    return mem

class MockMailClient:
    def poll_for_code(self, **kwargs):
        logger.info("[MockMail] Pretending to poll for code...")
        time.sleep(2)
        return "123456"

def run_test(iterations=3, proxy=None):
    logger.info(f"🚀 Starting Profile Test. Iterations: {iterations}, Proxy: {proxy}")
    
    initial_procs = get_process_count("chrom") # Matches chrome and chromium
    logger.info(f"Initial Chrome/Chromium Processes: {initial_procs}")
    
    def test_log_callback(level, msg):
        logger.info(f"[AutoLog] {msg}")

    automation = GeminiAutomation(headless=True, proxy=proxy, log_callback=test_log_callback)
    mock_mail = MockMailClient()
    
    for i in range(iterations):
        logger.info(f"\n--- Iteration {i+1}/{iterations} ---")
        start_mem = get_memory_usage()
        start_procs = get_process_count("chrom")
        
        logger.info(f"Start: Mem={start_mem:.2f}MB, ChromeProcs={start_procs}")
        
        try:
            # Mock email data
            email = f"test_debug_{int(time.time())}_{i}@gmail.com"
            logger.info(f"Running login_and_extract for {email}...")
            
            # NOTE: This will likely fail login because it's a fake email, 
            # but we want to see if the browser opens and CLOSES correctly.
            # We catch the error to proceed to cleanup check.
            try:
                result = automation.login_and_extract(email, mock_mail)
                logger.info(f"Result: {result}")
            except Exception as e:
                logger.error(f"Automation step failed (expected for fake data): {e}")
                
        except Exception as e:
            logger.error(f"Loop Exception: {e}")
            
        # Post-iteration check
        time.sleep(2) # Give a moment for cleanup
        end_mem = get_memory_usage()
        end_procs = get_process_count("chrom")
        
        diff_mem = end_mem - start_mem
        diff_procs = end_procs - start_procs
        
        logger.info(f"End: Mem={end_mem:.2f}MB, ChromeProcs={end_procs}")
        logger.info(f"Delta: Mem={diff_mem:+.2f}MB, ChromeProcs={diff_procs:+d}")
        
        if diff_procs > 0:
            logger.warning("⚠️ LEAK DETECTED: Chrome processes increased!")
        else:
            logger.info("✅ Process cleanup looks okay this round.")

    final_procs = get_process_count("chrom")
    logger.info(f"\nFinal Chrome Processes: {final_procs} (Started with {initial_procs})")
    
    if final_procs > initial_procs:
        logger.error(f"❌ TEST FAILED: Leaked {final_procs - initial_procs} processes overall.")
        
        # Dump details
        logger.info("--- Leaked Process Details ---")
        for proc in psutil.process_iter(['pid', 'ppid', 'name', 'status']):
            if "chrom" in proc.info['name'].lower():
                logger.info(f"PID={proc.info['pid']}, PPID={proc.info['ppid']}, Status={proc.info['status']}, Name={proc.info['name']}")
    else:
        logger.info("✅ TEST PASSED: No process leaks detected.")

if __name__ == "__main__":
    # Get proxy from env or args
    proxy_url = os.environ.get("TEST_PROXY")
    run_test(iterations=3, proxy=proxy_url)
