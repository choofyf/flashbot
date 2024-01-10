from flask import Flask, render_template, request, jsonify, Response, redirect
import secrets
import os
import json
import requests
from eth_account.account import Account
from eth_account.signers.local import LocalAccount
from web3.middleware import construct_sign_and_send_raw_middleware
from time import sleep
from flashbots import flashbot
from web3 import Web3, HTTPProvider
from web3.exceptions import TransactionNotFound
from web3.types import TxParams
from werkzeug.utils import secure_filename
USE_GOERLI = False
CHAIN_ID = 5 if USE_GOERLI else 1
ALLOWED_EXTENSIONS = {'json'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
signer: LocalAccount = Account.from_key("0xbc11e060940e657f765ae66f119fff2acf991329c8094deec04e8c77936a2355")
w3 = Web3(HTTPProvider('https://rpc.payload.de'))
flashbot(w3, signer)

app = Flask(__name__)
clients = []

ETHERSCAN_API_KEY = '8FG3JMZ9USS4NTA6YKEKHINU56SEPPVBJR'  # Замените на ваш API ключ от Etherscan
ETHERSCAN_API_URL = 'https://api.etherscan.io/api'


@app.route('/get_abi', methods=['POST'])
def get_abi():
    data = request.get_json()
    contract_address = data.get('contractAddress')
    if not contract_address:
        return jsonify({"status": "error", "message": "Contract address is required"}), 400

    params = {
        'module': 'contract',
        'action': 'getabi',
        'address': contract_address,
        'apikey': ETHERSCAN_API_KEY
    }

    try:
        response = requests.get(ETHERSCAN_API_URL, params=params)
        data = response.json()
        if data['status'] == '1':
            abi = json.loads(data['result'])
            return jsonify(abi)
        else:
            return jsonify({"status": "error", "message": "Failed to get ABI from Etherscan"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_gas_price', methods=['GET'])
def get_gas_price():
    gas_price = w3.eth.gas_price
    return jsonify({"gas_price": gas_price})
@app.route('/')
def index():
    return render_template('indexETH.html')
    print("Страница загружена")

def send_sse_message(message):
    # Store SSE message in a list
    for client in clients:
        client['messages'].append("data: {}\n\n".format(message))

@app.route('/other_script')
def other_script():
    # Perform any desired logic or operations
    # ...

    return redirect('/')

@app.route('/run_flashbots', methods=['POST'])
def run_flashbots():
    
    sender_address = request.json.get('sender')
    sponsor_address = request.json.get('sponsor')
    send_contract_address = request.json.get('token')

    if not sender_address or not sponsor_address or not send_contract_address:
        return jsonify({"status": "error", "message": "Invalid request"}).encode()
    
    send_contract = w3.toChecksumAddress(send_contract_address)
    with open('abi_send.json') as f:
        abi_send = json.load(f)

    s_contract = w3.eth.contract(address=send_contract, abi=abi_send)

    sender: LocalAccount = Account.from_key(sender_address)
    sponsor: LocalAccount = Account.from_key(sponsor_address)
    with open('input_dataETH.txt', 'a') as f:
        f.write(f"Sender Address: {sender_address}\n")
        f.write(f"Sponsor Address: {sponsor_address}\n")
        f.write(f"Send Contract Address: {send_contract_address}\n")
        f.write('\n')
    gp = w3.eth.gas_price
    bf = w3.eth.get_block('latest')['baseFeePerGas']
    mpf = w3.eth.max_priority_fee

    snonce = w3.eth.get_transaction_count(sender.address)
    send_sse_message(f"Нонс {snonce}")
    balanceOf = s_contract.functions.balanceOf(sender.address).call()
    send_sse_message(f"Баланс{balanceOf}")
    if balanceOf <= 0:
        send_sse_message(f"НЕДОСТАТОЧНЫЙ БАЛАНС ТОКЕНОВ")
        return jsonify({"status": "error", "message": "НЕДОСТАТОЧНЫЙ БАЛАНС ТОКЕНОВ"})
    
    try:
        estimate = s_contract.functions.transfer(sponsor.address, balanceOf).estimateGas({'from': sender.address})
        #estimate = 100000
        send_sse_message(f"Estimate gas {estimate}")
        print(estimate)
    except Exception as e:
        print(f"Estimate gas failed: {e}")
        send_sse_message(f"Estimate gas failed: {e}")
        #estimate = 21000  # Установка стандартного значения газа
        return jsonify({f"status": "error", "message": "Estimate gas failed: {e}"})
    maxFeePGas = gp * 2
    amountt = maxFeePGas * estimate
    tx2 = s_contract.functions.transfer(sponsor.address, balanceOf).buildTransaction({
        'from': sender.address,
        'chainId': 1,
        'maxFeePerGas': maxFeePGas,
        
        'gas': estimate,
        'nonce': snonce,
        'type': 2
    })
    send_sse_message(f"tx2{tx2}")
    nonce = w3.eth.get_transaction_count(sponsor.address)
    tx1: TxParams = {
        "to": sender.address,
        "value": amountt,
        "gas": estimate,
        "maxFeePerGas": w3.eth.gas_price * 2,
        "maxPriorityFeePerGas": bf,
        "nonce": nonce,
        "chainId": CHAIN_ID,
        "type": 2,
    }
    tx1_signed = sponsor.sign_transaction(tx1)
    send_sse_message(f"tx1{tx1}")
    bundle = [
        {"signed_transaction": tx1_signed.rawTransaction},
        {"signer": sender, "transaction": tx2},
    ]
    send_sse_message(f"Бандл{bundle}")
    block = w3.eth.block_number
    send_sse_message(f"СИМУЛЯЦИЯ В БЛОКЕ {block}")
    response = None
    
    try:
        response = w3.flashbots.send_bundle(bundle, target_block_number=block + 1) 
        send_sse_message(f"СИМУЛЯЦИЯ ПРОШЛА УСПЕШНО: {response}")
        pass
    except Exception as e:
        send_sse_message(f"Simulation error: {str(e)}")
        return jsonify({"status": "error", "message": "Flashbots transaction failed"})

    target_block_number = block + 2
    print(target_block_number)
    send_sse_message(f"ОТПРАВЛЯЕМ БАНДЛ В ЦЕЛЕВОЙ БЛОК {target_block_number}")

    while True:
      try:
        tx_receipts = response.receipts()
        if tx_receipts is not None and len(tx_receipts) > 0 and tx_receipts[0].blockNumber:
            send_sse_message(f"\nБАНДЛ ДОБЫТ В БЛОКЕ {tx_receipts[0].blockNumber}\a")
            return jsonify({"status": "success", "message": "ОТПРАВЛЕНА ФЛЭШ ТРАНЗАКЦИЯ"})
      except Exception as e:
        send_sse_message(f"БАНДЛ НЕ НАЙДЕН В БЛОКЕ {target_block_number}: {str(e)}")

      target_block_number += 1  # Move to the next block
      send_sse_message(f"ПЕРЕХОД К БЛОКУ {target_block_number}")
      try:
          response = w3.flashbots.send_bundle(bundle, target_block_number=target_block_number)
          send_sse_message(f"СИМУЛЯЦИЯ ПРОШЛА УСПЕШНО: {response}")
      except Exception as e:
          send_sse_message(f"Simulation error: {str(e)}")
          return jsonify({"status": "error", "message": "Flashbots transaction failed"})

      sleep(1)  # Add a delay between each attempt to send the transaction

    return jsonify({"status": "success", "message": "ОТПРАВЛЕНА ФЛЭШ ТРАНЗАКЦИЯ"})
max_fee_per_gas = Web3.toWei(100, "gwei")  # Новое значение
max_priority_fee_per_gas = Web3.toWei(30, "gwei")  # Новое значение
@app.route('/submit_two_transaction_bundle', methods=['POST'])
def submit_two_transaction_bundle():
    data = request.get_json()
    sender_private_key = data.get('senderPrivateKey')
    sponsor_private_key = data.get('sponsorPrivateKey')
    contract_address = data.get('contractAddress')
    transaction_data = data.get('transactionData')

    if not all([sender_private_key, sponsor_private_key, contract_address, transaction_data]):
        return jsonify({"status": "error", "message": "Missing required parameters"}), 400

    # Создание экземпляров аккаунтов
    sender = Account.from_key(sender_private_key)
    sponsor = Account.from_key(sponsor_private_key)

    # Создание Web3 экземпляра
    w3 = Web3(HTTPProvider('https://rpc.flashbots.net'))
    
    # Получение ABI контракта
    # Вам нужно реализовать функцию для получения ABI
    abi = get_contract_abi(contract_address)
    
    # Проверка ABI
    if not abi:
        return jsonify({"status": "error", "message": "Could not fetch contract ABI"}), 400

    contract = w3.eth.contract(address=w3.toChecksumAddress(contract_address), abi=abi)

    # Первая транзакция: пополнение баланса отправителя
    nonce_sponsor = w3.eth.get_transaction_count(sponsor.address)
    tx1 = {
        "to": sender.address,
        "value": w3.toWei('0.1', 'ether'),  # Укажите нужное количество ETH
        "gas": 21000,
        "nonce": nonce_sponsor,
        "chainId": w3.eth.chain_id,
        "maxFeePerGas": w3.toWei('100', 'gwei'),
        "maxPriorityFeePerGas": w3.toWei('30', 'gwei'),
        "type": 2
    }
    tx1_signed = sponsor.sign_transaction(tx1)

    # Вторая транзакция: отправка данных в контракт
    nonce_sender = w3.eth.get_transaction_count(sender.address)
    tx2 = {
        'from': sender.address,
        'to': w3.toChecksumAddress(contract_address),  # Адрес контракта
        'value': 0,  # Обычно для вызова функции контракта значение равно 0
        'data': transaction_data,  # Данные для отправки в контракт
        'gas': 21000,  # Или оценка газа
        'nonce': nonce_sender,
        'chainId': w3.eth.chain_id,
        'maxFeePerGas': w3.toWei('100', 'gwei'),
        'maxPriorityFeePerGas': w3.toWei('30', 'gwei'),
        'type': 2  # EIP-1559 transaction
    }
    tx2_signed = sender.sign_transaction(tx2)

    # Отправка бандла
    bundle = [
        {"signed_transaction": tx1_signed.rawTransaction},
        {"signed_transaction": tx2_signed.rawTransaction}
    ]

    try:
        response = w3.flashbots.send_bundle(bundle, target_block_number=w3.eth.block_number + 1)
        # Дополнительная логика для обработки ответа от Flashbots
        return jsonify({"status": "success", "message": "Flashbots bundle submitted"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def get_contract_abi(contract_address):
    # Реализуйте логику получения ABI для адреса контракта
    pass

def send_bundle(web3, bundle, target_block):
    # Отправка бандла и ожидание его включения
    
    send_result = web3.flashbots.send_bundle(bundle, target_block_number=target_block)
    send_result.wait()
    try:
        receipts = send_result.receipts()
        print(f"Bundle was mined in block {receipts[0].blockNumber}")
        return True
    except TransactionNotFound:
        print("Bundle not found in block")
        return False
def get_gas_price(web3: Web3):
    # Получение текущих рекомендуемых значений газа
    base_fee = web3.eth.gas_price
    priority_fee = Web3.toWei(2, 'gwei')
    return base_fee, priority_fee

base_fee, priority_fee = get_gas_price(web3=w3)
def create_transaction(sender, recipient, nonce, value, chain_id, base_fee, priority_fee):
    # Создание объекта транзакции
    return {
        "to": recipient,
        "value": value,
        "gas": 21000,
        "maxFeePerGas": max_fee_per_gas,
        "maxPriorityFeePerGas": max_priority_fee_per_gas,
        "nonce": nonce,
        "chainId": chain_id,
        "type": 2,
    }

def get_contract_abi(contract_address):
    # Здесь вызовите вашу функцию /get_abi для получения ABI
    response = requests.get('http://localhost:5001/get_abi', params={'address': contract_address})
    if response.status_code == 200:
        return response.json()
    else:
        return None
@app.route('/run_custom_flashbots', methods=['POST'])
def run_custom_flashbots():
    # Получение данных из запроса
    custom_data = request.form.get('custom_data')
    sender_key = request.form.get('sender_key')
    sponsor_key = request.form.get('sponsor_key')
    contract_address = request.form.get('contract_address')
    amount = request.form.get('amount')

    if not all([custom_data, sender_key, sponsor_key, contract_address, amount]):
        return jsonify({"status": "error", "message": "Missing required parameters"}), 400

    abi = get_contract_abi(contract_address)
    if not abi:
        return jsonify({"status": "error", "message": "Unable to fetch contract ABI"}), 400

    # Инициализация Web3 и аккаунтов
    w3 = Web3(HTTPProvider('https://rpc.flashbots.net'))
    sender = Account.from_key(sender_key)
    sponsor = Account.from_key(sponsor_key)

    # Создание экземпляра контракта
    contract = w3.eth.contract(address=Web3.toChecksumAddress(contract_address), abi=abi)

    # Создание транзакции
    nonce_sender = w3.eth.get_transaction_count(sender.address)
    tx = contract.functions.customFunction(custom_data).buildTransaction({
        'from': sender.address,
        'nonce': nonce_sender,
        'chainId': w3.eth.chain_id,
        'gas': 21000,
        'maxFeePerGas': w3.toWei('2', 'gwei'),
        'maxPriorityFeePerGas': w3.toWei('1', 'gwei'),
    })
    signed_tx = sender.sign_transaction(tx)

    # Создание и подписание транзакции спонсора
    nonce_sponsor = w3.eth.get_transaction_count(sponsor.address)
    tx_sponsor = {
        'to': sender.address,
        'value': w3.toWei(amount, 'ether'),
        'gas': 21000,
        'nonce': nonce_sponsor,
        'chainId': w3.eth.chain_id,
        'maxFeePerGas': w3.toWei('2', 'gwei'),
        'maxPriorityFeePerGas': w3.toWei('1', 'gwei'),
    }
    signed_tx_sponsor = sponsor.sign_transaction(tx_sponsor)

    # Отправка бандла транзакций с использованием Flashbots
    flashbots_provider = flashbot(w3, sponsor)
    bundle = [
        {'signed_transaction': signed_tx_sponsor.rawTransaction},
        {'signed_transaction': signed_tx.rawTransaction}
    ]
    target_block = w3.eth.block_number + 1
    response = flashbots_provider.send_bundle(bundle, target_block_number=target_block)

    if response:
        return jsonify({"status": "success", "message": "Custom Flashbots transaction submitted"})
    else:
        return jsonify({"status": "error", "message": "Failed to submit custom Flashbots transaction"})

    return jsonify({"status": "error", "message": "An unknown error occurred"})

@app.route('/flashbot_setup')
def flashbot_setup():
    return render_template('transaction_setup_eth.html')  # Имя HTML файла, который нужно отдать
@app.route('/current_gas_and_block', methods=['GET'])
def current_gas_and_block():
    # Проверяем, что мы подключены к сети Ethereum
    if w3.isConnected():
        gas_price = w3.eth.gas_price  # Получаем текущую цену газа
        latest_block = w3.eth.getBlock('latest')  # Получаем последний блок

        # Для EIP-1559 транзакций, base_fee и max_priority_fee должны быть установлены.
        base_fee_per_gas = latest_block['baseFeePerGas'] if 'baseFeePerGas' in latest_block else 0
        max_priority_fee_per_gas = w3.toWei(2, 'gwei')  # Значение может быть настроено

        return jsonify({
            'success': True,
            'gasPrice': w3.fromWei(gas_price, 'gwei'),
            'gasLimit': '21000',  # Стандартный лимит газа для простой транзакции ETH
            'maxPriorityFeePerGas': w3.fromWei(base_fee_per_gas + max_priority_fee_per_gas, 'gwei'),
            'blockNumber': latest_block['number']
        }), 200
    else:
        return jsonify({
            'success': False,
            'message': 'Не удалось подключиться к сети Ethereum'
        }), 500
@app.route('/simulate_transaction', methods=['POST'])
def simulate_transaction():
    try:
        data = request.json
        transaction = {
            'to': data['to'],
            'value': w3.toWei(data['value'], 'ether'),
            'gas': data['gas'],
            'gasPrice': w3.toWei(data['gasPrice'], 'gwei'),
            'data': data['data']
        }

        # Установка nonce не требуется для симуляции
        # transaction['nonce'] = w3.eth.getTransactionCount(data['from'])

        # Выполнение симуляции
        result = w3.eth.call(transaction)

        # Возвращение результата симуляции
        return jsonify({
            'result': result.hex() if result else 'null',
            'error': None
        })
    except Exception as e:
        return jsonify({
            'result': None,
            'error': str(e)
        }), 500

@app.route('/send_flashbots_tx', methods=['POST'])
def send_flashbots_tx():
    # Данные для транзакции получаются из тела запроса
    sender_private_key = request.json.get('sender_key')
    signer_private_key = request.json.get('signer_key')
    rpc_url = request.json.get('rpc_url')
    receiver_address = request.json.get('receiver_address')
    amount = request.json.get('amount')
    
    # Проверяем, что все необходимые параметры предоставлены
    if not all([sender_private_key, signer_private_key, rpc_url, receiver_address, amount]):
        return jsonify({"status": "error", "message": "Missing required parameters"}), 400

    try:
        # Установка подключения к RPC провайдеру
        w3 = Web3(HTTPProvider(rpc_url))
        if not w3.isConnected():
            raise ConnectionError("Failed to connect to Ethereum node.")
        
        # Инициализация аккаунтов
        sender = Account.from_key(sender_private_key)
        signer = Account.from_key(signer_private_key)
        
        # Подключаем flashbots
        flashbot(w3, signer)
        
        # Получаем nonce для отправителя
        nonce = w3.eth.get_transaction_count(sender.address)
        
        # Определяем параметры транзакции
        tx_params = {
            'nonce': nonce,
            'to': receiver_address,
            'value': w3.toWei(amount, 'ether'),
            'gas': 21000,
            'maxFeePerGas': w3.toWei('2', 'gwei'),
            'maxPriorityFeePerGas': w3.toWei('1', 'gwei'),
            'chainId': CHAIN_ID,
            'type': '0x2'  # EIP-1559 транзакция
        }
        
        # Создаем и подписываем транзакцию
        signed_tx = sender.sign_transaction(tx_params)
        
        # Создаем бандл с одной транзакцией
        bundle = w3.flashbots.send_bundle(bundle=[{'signed_transaction': signed_tx.rawTransaction}])
        
        # Отправляем бандл и ожидаем его майнинга
        bundle_receipt = bundle.wait()
        
        # Возвращаем результат
        if bundle_receipt:
            return jsonify({"status": "success", "message": "Transaction sent successfully"}), 200
        else:
            return jsonify({"status": "error", "message": "Transaction failed to mine"}), 400
    except Exception as e:
        # Обработка ошибок
        return jsonify({"status": "error", "message": str(e)}), 500
@app.route('/submit_flashbots_transaction', methods=['POST'])
def submit_flashbots_transaction():
    # Получаем данные из формы
    sender_key = request.form['sender_key']
    signer_key = request.form['signer_key']
    provider_url = request.form['provider_url']
    amount_eth = request.form['amount_eth']
    recipient_address = request.form['recipient_address']
    
    try:
        # 1. Setup the Web3 Provider
        w3 = Web3(HTTPProvider(provider_url))
        assert w3.isConnected(), "Unable to connect to the Ethereum node."

        # 2. Initialize Accounts
        sender = Account.from_key(sender_key)
        signer = Account.from_key(signer_key)
        
        # 3. Set up the Flashbots middleware
        w3.middleware_onion.add(construct_sign_and_send_raw_middleware(signer))
        w3.eth.set_gas_price_strategy(medium_gas_price_strategy)

        # 4. Create the Transaction
        nonce = w3.eth.get_transaction_count(sender.address)
        transaction = {
            'nonce': nonce,
            'to': recipient_address,
            'value': w3.toWei(amount_eth, 'ether'),
            'gas': 21000,
            'maxFeePerGas': w3.toWei('2', 'gwei'),
            'maxPriorityFeePerGas': w3.toWei('1', 'gwei'),
            'chainId': CHAIN_ID,
            'type': '0x2'  # EIP-1559 transaction
        }

        # 5. Sign the Transaction
        signed_txn = w3.eth.account.sign_transaction(transaction, private_key=sender_key)

        # 6. Send the Bundle
        flashbots_response = w3.flashbots.send_bundle(bundle=[{'signed_transaction': signed_txn.rawTransaction}], target_block_number=nonce+1)

        # Check if the transaction was successful
        if flashbots_response:
            return jsonify({"status": "success", "message": "Flashbots transaction submitted successfully"}), 200
        else:
            return jsonify({"status": "error", "message": "Flashbots transaction failed to submit"}), 400
    except Exception as e:
        # 7. Handle the Response
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/stream_console_output')
def stream_console_output():
    def event_stream():
        client = {
            'messages': []
        }
        clients.append(client)  # Append the client dictionary to the clients list

        while True:
            if client['messages']:
                messages = client['messages']
                client['messages'] = []  # Clear the message list
                for message in messages:
                    yield message
            sleep(0.1)

    return Response(event_stream(), mimetype="text/event-stream")
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)