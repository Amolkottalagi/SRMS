import os
import sys
# pyrefly: ignore [missing-import]
from pyngrok import ngrok

def start_public_server():
    # Check for token
    token = os.environ.get("NGROK_AUTHTOKEN")
    if not token:
        print("=" * 60)
        print("WARNING: NGROK_AUTHTOKEN environment variable is not set.")
        print("Please sign up at https://ngrok.com/ to get your free authtoken,")
        print("then set it as an environment variable or enter it below.")
        print("=" * 60)
        token = input("Enter your Ngrok Authtoken (or press Enter to skip if already configured via CLI): ").strip()

    if token:
        ngrok.set_auth_token(token)

    # Start the tunnel
    try:
        # Port 5000 is default for our FastAPI app
        public_url = ngrok.connect(5000)
        print("\n" + "=" * 60)
        print(f" * Public URL: {public_url.public_url}")
        print(" * You can share this URL with anyone to access your local server!")
        print("=" * 60 + "\n")
    except Exception as e:
        print(f"Error starting Ngrok tunnel: {e}")
        print("Please make sure Ngrok is configured correctly or your Authtoken is valid.")
        sys.exit(1)

    # Now run the FastAPI app
    import uvicorn
    from app import app, seed_database
    seed_database()
    uvicorn.run(app, host="0.0.0.0", port=5000)

if __name__ == "__main__":
    start_public_server()
