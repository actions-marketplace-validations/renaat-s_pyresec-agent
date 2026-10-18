from web3 import Web3
w3 = Web3(Web3.HTTPProvider('https://mainnet.base.org'))
USDC = Web3.to_checksum_address('0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913')
ABI = [{"name":"balanceOf","type":"function","inputs":[{"name":"a","type":"address"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"}]
usdc = w3.eth.contract(address=USDC, abi=ABI)
test = usdc.functions.balanceOf(Web3.to_checksum_address('0xa97dF9D3752CD96744c0322371dAEC878D284358')).call()
main = usdc.functions.balanceOf(Web3.to_checksum_address('0x9FB752Ee45d609820E88C2b8153322f8c5B98239')).call()
print(f"Test wallet USDC: ${test/1e6:.6f}")
print(f"Main wallet USDC: ${main/1e6:.6f}")
