import threading
from flask import Flask, render_template, request, Response, jsonify, redirect
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account.account import Account
import time
import requests
import datetime
import json
import os
from hexbytes import HexBytes
from requests.structures import CaseInsensitiveDict

app = Flask(__name__)
lock = threading.Lock()
BSCSCAN_API_KEY = 'Q26ZVJUIWW52Y7VVI3TPQCJNH5PGI14EV8'
BSCSCAN_API_URL = 'https://api.bscscan.com/api'
clients = [] 
def send_sse_message(message):
    # Store SSE message in a list
    for client in clients:
        client['messages'].append("data: {}\n\n".format(message))
        client['console_messages'].append(message)  # Add the message to the console messages list

class HexJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, HexBytes):
            return obj.hex()
        return super().default(obj)

headers = CaseInsensitiveDict()
headers["Accept"] = "application/json"
headers["Content-Type"] = "application/json"

url = "https://puissant-bsc.bnb48.club"

notify_msgg = 'https://api.telegram.org/bot6049821309:AAETYRCvxwMqH-6tRKlaiQf1M_Kn1Us5uTU/sendMessage?chat_id=5680208836&text='

def txt2list(fname):
    with open(fname, 'r', encoding="utf8") as f:
        return [line.strip() for line in f]

result_list = []
send_pussy_list = []

web3 = Web3(Web3.HTTPProvider('https://endpoints.omniatech.io/v1/bsc/mainnet/public'))
web3.middleware_onion.inject(geth_poa_middleware, layer=0)

def init_check_contract(web3):
    check_contract_addr = Web3.toChecksumAddress('0x5971bE05F8ae6Db51971Be8A31508932aAFDA749')  # opencontract
    with open('check_abi.json') as f:
        check_abi = json.loads(f.read())
    check_contract = web3.eth.contract(address=check_contract_addr, abi=check_abi)
    return check_contract

def init_contract(web3, address_of_token):
    token_contract_usdt = Web3.toChecksumAddress(address_of_token)
    if not web3.isChecksumAddress(token_contract_usdt):
        print("Invalid contract address:", address_of_token)
        return None

    with open('abi.json') as f:
        abi = json.loads(f.read())
    contract_usdt = web3.eth.contract(address=token_contract_usdt, abi=abi)
    return contract_usdt
@app.route('/get_abi', methods=['POST'])
def get_abi():
    data = request.json
    contract_address = data['contractAddress']
    
    params = {
        'module': 'contract',
        'action': 'getabi',
        'address': contract_address,
        'apikey': BSCSCAN_API_KEY
    }
    
    response = requests.get(BSCSCAN_API_URL, params=params)
    response_json = response.json()

    if response_json['status'] == '1':
        abi = response_json['result']
        return jsonify({'abi': abi})
    else:
        return jsonify({'error': 'Unable to fetch ABI'}), 400
@app.route('/')
def index():
    return render_template('indexBSC.html')
@app.route('/console')
def console():
    return jsonify(result_list + send_pussy_list)

@app.route('/submit', methods=['POST', 'GET'])
def send_sendPuissant():
    if request.method == 'POST':
        try:
            sponsor_private_key = request.form['sponsor_private_key']
            sender_private_key = request.form['sender_private_key']
            token_contract_address = request.form['token_address']
            # Получаем пользовательские вводы для газа
            gas_price_input = request.form.get('gas_price', '5')  # Значение по умолчанию 5 Gwei
            gas_limit_input = request.form.get('gas_limit', '21000')  # Значение по умолчанию 21000

            # Преобразование введенных значений в соответствующий формат
            gas_price = Web3.toWei(gas_price_input, 'gwei')
            gas_limit = int(gas_limit_input)

            token_contract_address = Web3.toChecksumAddress(token_contract_address)
            token_contract = init_contract(web3, token_contract_address)

            sender = Account.from_key(sender_private_key)
            sponsor = Account.from_key(sponsor_private_key)

            gasPrice = gas_price  # Используем введенную пользователем цену газа
            nonce2 = web3.eth.getTransactionCount(sender.address)
            amount = token_contract.functions.balanceOf(sender.address).call()
            # Оценка газа использует лимит газа, введенный пользователем
            estimate = gas_limit  

            tx2 = token_contract.functions.transfer(sponsor.address, amount).buildTransaction({
                'from': sender.address, 'chainId': 56, 'gas': estimate, 'gasPrice': gasPrice, 'nonce': nonce2
            })
            signed_tx2 = sender.sign_transaction(tx2)
            ttt2 = signed_tx2.rawTransaction.hex()

            send_amount = estimate * gasPrice

            nonce = web3.eth.getTransactionCount(sponsor.address)
            tx = {
                'chainId': 56, 'nonce': nonce, 'to': sender.address, 'value': send_amount,
                'gas': gas_limit,  # Используем лимит газа, введенный пользователем
                'gasPrice': gas_price  # Используем цену газа, введенную пользователем
            }
            signed_tx = sponsor.sign_transaction(tx)
            ttt1 = signed_tx.rawTransaction.hex()

            # Отправляем SSE сообщение с деталями газа
            send_sse_message(f"Цена газа: {gas_price_input} Gwei, Лимит газа: {gas_limit_input}")

            # Отправка транзакций
            latest_block_number = web3.eth.block_number - 1
            block = web3.eth.get_block(latest_block_number)
            timestamp = block.timestamp
            dt = datetime.datetime.fromtimestamp(timestamp) + datetime.timedelta(minutes=2)
            uint64_timestamp = int(dt.timestamp())

            payload = {
                "jsonrpc": "2.0",
                "method": "eth_sendPuissant",
                "params": [
                    {
                        "txs": [ttt1, ttt2],
                        "maxTimestamp": uint64_timestamp
                    }
                ],
                "id": 1
            }

            response = requests.post(url, headers=headers, json=payload)
            send_sse_message(f"Статус ответа {response.status_code}")
            
            if response.status_code == 200 and "result" in response.text:
                result = response.json()["result"]
                explorer_url = f"https://explorer.48.club/api/v1/puissant/{result}"
                send_sse_message(explorer_url)
                send_pussy_list.append(explorer_url)
                print("Отправленно")
            else:
                send_sse_message(response.text)
                send_sse_message("Ошибка при отправке транзакции")

        except Exception as e:
            send_sse_message(f"Ошибка при выполнении транзакции: {str(e)}")
            return jsonify({"status": "error", "message": str(e)})

        return stream_console_output()
    else:
        # Если метод не POST, просто вернем страницу
        return redirect(url_for('index'))


@app.route('/stream_console_output')
def stream_console_output():
    def event_stream():
        client = {
            'messages': [],
            'console_messages': []  # Add a new key 'console_messages' to store console output
        }
        clients.append(client)  # Append the client dictionary to the clients list

        while True:
            if client['messages']:
                messages = client['messages']
                client['messages'] = []  # Clear the message list
                for message in messages:
                    yield message
            if client['console_messages']:
                console_messages = client['console_messages']
                client['console_messages'] = []  # Clear the console messages list
                for console_message in console_messages:
                    yield console_message + "\n"  # Yield the console message with a newline character
            time.sleep(0.1)

    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=50002, debug=False)
