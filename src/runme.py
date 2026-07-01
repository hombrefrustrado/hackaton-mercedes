import sys
import os

# Add the directory containing runme.py (src/) to the Python path
# to ensure the 'app' module resolves correctly regardless of how this script is run.
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app import app

if __name__ == "__main__":
    # Start the Flask app
    app.run(host="0.0.0.0", port=8000, debug=True)
