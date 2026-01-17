from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient(host="127.0.0.1", port=5020)

if client.connect():
    result = client.read_holding_registers(address=0, count=20)

    if not result.isError():
        print("Registers:", result.registers)
    else:
        print("Modbus read error:", result)

    client.close()
else:
    print("Could not connect to Modbus server.")
