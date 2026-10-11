"""One-time Mac Keychain setup; no API validation request or plaintext key file."""
import getpass
import shlex
import subprocess


def main():
    key = getpass.getpass("ElevenLabs key to save securely in Mac Keychain: ").strip()
    if not key:
        raise SystemExit("No key supplied; nothing changed.")
    # Pass the credential through stdin, not process arguments or shell history.
    command = "add-generic-password -U -s skytrace.elevenlabs -a api-key -w " + shlex.quote(key) + "\n"
    result = subprocess.run(["security", "-i"], input=command, text=True, capture_output=True)
    if result.returncode or "error" in result.stderr.lower():
        raise SystemExit("Could not save the key. Unlock your login Keychain and try again.")
    print("Saved securely. Start code/main.py normally; no key prompt is needed.")


if __name__ == "__main__":
    main()
