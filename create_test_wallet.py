"""
PYRESEC Test Wallet Generator & Funder
Creates a throwaway client wallet and funds it with $1 USDC from the main wallet.
"""
import os, sys
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

load_dotenv()

RPC_URL = "https://mainnet.base.org"
MAIN_PRIVATE_KEY = os.getenv("CDP_WALLET_SECRET")
USDC = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")

ERC20_ABI = [
    {"name":"balanceOf","type":"function","inputs":[{"name":"a","type":"address"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"},
    {"name":"transfer","type":"function","inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],"outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable"},
    {"name":"decimals","type":"function","inputs":[],"outputs":[{"name":"","type":"uint8"}],"stateMutability":"view"},
]

def main():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    main_account = Account.from_key(MAIN_PRIVATE_KEY)
    main_addr = main_account.address
    
    print("=== PYRESEC Test Wallet Generator ===\n")
    print(f"Main wallet: {main_addr}")
    
    # Check main wallet USDC balance
    usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
    main_usdc = usdc.functions.balanceOf(main_addr).call() / 1e6
    print(f"Main USDC: ${main_usdc:.6f}")
    
    if main_usdc < 1.0:
        print(f"ERROR: Need at least $1 USDC to fund test wallet. Have ${main_usdc:.6f}")
        sys.exit(1)
    
    # Generate throwaway test wallet
    test_wallet = Account.create()
    test_addr = test_wallet.address
    test_key = test_wallet.key.hex()
    
    print(f"\n--- New Test Wallet ---")
    print(f"Address:  {test_addr}")
    print(f"Privkey:  {test_key}")
    
    # Transfer $1 USDC to test wallet
    print(f"\nFunding test wallet with $1.00 USDC...")
    
    main_usdc_contract = w3.eth.contract(address=USDC, abi=ERC20_ABI)
    amount = 1_000_000  # $1 = 1,000,000 base units (6 decimals)
    
    nonce = w3.eth.get_transaction_count(main_addr)
    gas_price = w3.eth.gas_price
    
    tx = main_usdc_contract.functions.transfer(
        Web3.to_checksum_address(test_addr),
        amount
    ).build_transaction({
        "from": main_addr,
        "gas": 100000,
        "gasPrice": gas_price,
        "nonce": nonce,
        "chainId": 8453,
    })
    
    signed = w3.eth.account.sign_transaction(tx, MAIN_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"TX: {tx_hash.hex()}")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    
    if receipt.status == 1:
        print(f"SUCCESS! Confirmed in block {receipt.blockNumber}")
        
        test_usdc = usdc.functions.balanceOf(test_addr).call() / 1e6
        print(f"\nTest wallet USDC: ${test_usdc:.6f}")
        
        # Save to .env.test_client
        env_path = os.path.join(os.path.dirname(__file__), ".env.test_client")
        with open(env_path, "w") as f:
            f.write(f"# Throwaway test client wallet - DO NOT COMMIT\n")
            f.write(f"TEST_CLIENT_PRIVATE_KEY={test_key}\n")
            f.write(f"TEST_CLIENT_ADDRESS={test_addr}\n")
            f.write(f"FUNDED_AMOUNT=1.00\n")
            f.write(f"FUNDED_TX={tx_hash.hex()}\n")
        
        print(f"\nSaved to: {env_path}")
        print(f"\n=== DONE ===")
        print(f"Test client wallet ready: {test_addr}")
        print(f"Server wallet (receives payments): {main_addr}")
    else:
        print(f"TRANSFER FAILED! TX: https://basescan.org/tx/{tx_hash.hex()}")
        sys.exit(1)

if __name__ == "__main__":
    main()
