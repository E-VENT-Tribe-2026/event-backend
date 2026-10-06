import argparse
from getpass import getpass

import httpx


def error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return str(detail or f"HTTP {response.status_code}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactively smoke-test the E-VENT AI assistant API.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Backend base URL (default: http://127.0.0.1:8000)",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    email = input("Account email: ").strip()
    password = getpass("Account password: ")

    try:
        with httpx.Client(timeout=30.0) as client:
            login = client.post(
                f"{base_url}/api/auth/login",
                json={"email": email, "password": password},
            )
            if not login.is_success:
                print(f"Login failed: {error_message(login)}")
                return 1

            access_token = login.json().get("access_token")
            if not access_token:
                print("Login response did not contain an access token.")
                return 1

            headers = {"Authorization": f"Bearer {access_token}"}
            messages: list[dict[str, str]] = []

            print("Signed in. Type /exit to end the session.")
            while True:
                user_text = input("You: ").strip()
                if user_text.lower() in {"/exit", "/quit"}:
                    return 0
                if not user_text:
                    continue
                if len(user_text) > 2000:
                    print("Message is too long (maximum 2000 characters).")
                    continue

                messages.append({"role": "user", "content": user_text})
                messages = messages[-20:]

                try:
                    response = client.post(
                        f"{base_url}/api/assistant/chat",
                        headers=headers,
                        json={"messages": messages},
                    )
                except httpx.RequestError as exc:
                    print(f"Assistant request failed: {exc}")
                    messages.pop()
                    continue

                if not response.is_success:
                    print(f"Assistant request failed: {error_message(response)}")
                    messages.pop()
                    continue

                reply = response.json().get("reply")
                if not isinstance(reply, str) or not reply.strip():
                    print("Assistant returned an empty or invalid reply.")
                    messages.pop()
                    continue

                print(f"Assistant: {reply}")
                messages.append({"role": "assistant", "content": reply[:2000]})

    except httpx.RequestError as exc:
        print(f"Could not connect to {base_url}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())