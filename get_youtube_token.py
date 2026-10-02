"""Run once on your own PC to get a YouTube refresh token (only needed for UPLOAD_MODE=api).

1. Google Cloud Console -> new project -> enable "YouTube Data API v3"
2. OAuth consent screen: External, add yourself as a test user
3. Credentials -> Create OAuth client ID -> Desktop app -> download JSON as client_secret.json
4. python get_youtube_token.py   (a browser opens; pick the account that owns the channel)
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nAdd these as GitHub secrets (or to .env):\n")
print(f"YT_CLIENT_ID={creds.client_id}")
print(f"YT_CLIENT_SECRET={creds.client_secret}")
print(f"YT_REFRESH_TOKEN={creds.refresh_token}")
print("\nNote: while the consent screen is in 'Testing' mode the token expires after 7 days."
      "\nSet the app to 'In production' (no review needed for your own account) to keep it.")
