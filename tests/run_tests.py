"""
Simple test runner script to verify core functionality
Run this after installing dependencies: pip install -r requirements.txt
"""

import subprocess
import sys

def main():
    print("🧪 Running Unit Tests...")
    print("=" * 60)
    
    try:
        # Run pytest with verbose output
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
            capture_output=False,
            text=True
        )
        
        if result.returncode == 0:
            print("\n" + "=" * 60)
            print("✅ All tests passed!")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ Some tests failed. See output above.")
            print("=" * 60)
            sys.exit(1)
            
    except FileNotFoundError:
        print("❌ pytest not found. Install dependencies first:")
        print("   pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
