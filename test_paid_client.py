import os
import sys
import json
import requests
from eth_account import Account
from dotenv import load_dotenv
from web3 import Web3

from x402.clients import x402Client
from x402.types import PaymentRequirements

load_dotenv()
TEST_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.test_client")
load_dotenv(TEST_ENV)

PYRESEC_URL = os.getenv("PYRESEC_URL", "https://pyresec-agent-519576377065.us-central1.run.app")
QUICK_SCAN_ENDPOINT = f"{PYRESEC_URL}/v1/audit/quick-scan"

TEST_CODE = {"code": "def evaluate(input): eval(input)"}

CLIENT_PRIVATE_KEY = os.getenv("TEST_CLIENT_PRIVATE_KEY")
SERVER_WALLET = "0x17eA81BF3bD47Fb6524a09a52DBB77fe1f4ab687"
RPC_URL = "https://mainnet.base.org"
USDC_ADDRESS = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
USDC_ABI = [
    {"name": "balanceOf", "type": "function", "inputs": [{"name": "account", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view"},
]

def get_usdc_balance(address):
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    usdc = w3.eth.contract(address=USDC_ADDRESS, abi=USDC_ABI)
    return usdc.functions.balanceOf(Web3.to_checksum_address(address)).call() / 1e6

def get_eth_balance(address):
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    return w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(address)), "ether")

def main():
    if not CLIENT_PRIVATE_KEY:
        print("ERROR: TEST_CLIENT_PRIVATE_KEY not set. Run create_test_wallet.py first.")
        sys.exit(1)

    client_account = Account.from_key(CLIENT_PRIVATE_KEY)
    client_addr = client_account.address

    print("=" * 60)
    print("PYRESEC x402 Payment Test (Separate Wallets)")
    print("=" * 60)

    print("\n[1/5] Balances BEFORE...")
    client_usdc = get_usdc_balance(client_addr)
    client_eth = get_eth_balance(client_addr)
    server_usdc = get_usdc_balance(SERVER_WALLET)
    print(f"  Client (payer):   {client_addr[:10]}...{client_addr[-6:]}")
    print(f"    USDC: ${client_usdc:.6f} | ETH: {client_eth:.6f}")
    print(f"  Server (payee):   {SERVER_WALLET[:10]}...{SERVER_WALLET[-6:]}")
    print(f"    USDC: ${server_usdc:.6f}")

    if client_usdc < 0.01:
        print(f"\n  ERROR: Client wallet has insufficient USDC (${client_usdc:.6f}). Need at least $0.01.")
        sys.exit(1)

    print("\n[2/5] Sending unpaid request to /v1/audit/quick-scan...")
    resp = requests.post(QUICK_SCAN_ENDPOINT, json=TEST_CODE)
    print(f"  Status: {resp.status_code} {resp.reason}")

    if resp.status_code != 402:
        print(f"  ERROR: Expected 402, got {resp.status_code}")
        sys.exit(1)

    challenge = resp.json()
    accepts = challenge.get("accepts", [])
    if not accepts:
        print("  ERROR: No payment requirements in 402 response")
        sys.exit(1)

    payment_req_data = accepts[0]
    print(f"  payTo:    {payment_req_data.get('payTo')}")
    print(f"  amount:   {payment_req_data.get('maxAmountRequired')} (USDC base units)")
    print(f"  asset:    {payment_req_data.get('asset')}")
    print(f"  network:  {payment_req_data.get('network')}")

    print("\n[3/5] Creating x402 payment header with CLIENT wallet...")
    payment_req_data["extra"] = {k: v for k, v in payment_req_data.get("extra", {}).items() if isinstance(v, str) and v.isascii()}
    payment_requirements = PaymentRequirements(
        scheme=payment_req_data.get("scheme", "exact"),
        network=payment_req_data.get("network", "base"),
        max_amount_required=payment_req_data.get("maxAmountRequired", "10000"),
        resource=payment_req_data.get("resource", QUICK_SCAN_ENDPOINT),
        description=payment_req_data.get("description", ""),
        mime_type=payment_req_data.get("mimeType", ""),
        pay_to=payment_req_data.get("payTo"),
        max_timeout_seconds=payment_req_data.get("maxTimeoutSeconds", 300),
        asset=payment_req_data.get("asset"),
        extra=payment_req_data.get("extra", {})
    )

    x402_client = x402Client(account=client_account)
    payment_header = x402_client.create_payment_header(payment_requirements)
    print(f"  Payment header created ({len(payment_header)} chars)")

    print("\n[4/5] Sending PAID request...")
    headers = {"Content-Type": "application/json", "X-PAYMENT": payment_header}
    paid_resp = requests.post(QUICK_SCAN_ENDPOINT, json=TEST_CODE, headers=headers)
    print(f"  Status: {paid_resp.status_code} {paid_resp.reason}")

    if paid_resp.status_code == 200:
        result = paid_resp.json()
        print("\n[5/5] AUDIT RESULT:")
        print("-" * 60)
        print(json.dumps(result, indent=2))
        print("-" * 60)
    else:
        print(f"  Response: {paid_resp.text[:500]}")

    print("\n[BALANCE CHECK] Balances AFTER...")
    client_usdc_new = get_usdc_balance(client_addr)
    server_usdc_new = get_usdc_balance(SERVER_WALLET)
    print(f"  Client: ${client_usdc_new:.6f} (spent: ${client_usdc - client_usdc_new:.6f})")
    print(f"  Server: ${server_usdc_new:.6f} (earned: ${server_usdc_new - server_usdc:.6f})")

    print("\n" + "=" * 60)
    print("Test complete.")
    print("=" * 60)

if __name__ == "__main__":
    main()
