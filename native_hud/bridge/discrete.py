"""Discrete actions via the proven sendmsg pipeline (GameClient.SendRoomMessageAsync).
All are SimpleClientPact{type, param?}. Wire format confirmed by tracing real clicks.
  breakthrough        SimpleClientPact{type=2}
  ready               SimpleClientPact{type=3}
  selecttalent <id>   SimpleClientPact{type=5, param=id}   (选天衍/仙命)
  selectdaoyun <id>   SimpleClientPact{type=9, param=id}
Usage: discrete.py <action> [id]
"""
import sys, base64, frida

AG = r"F:\桌面\弈仙牌外挂\_recon_hotfix\cverify\bot_glue3.agent.js"

def varint(n):
    out = b""
    while True:
        b = n & 0x7F; n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n: return out

def pact(type_, param=None):
    """SimpleClientPact: field1=type (varint), field2=param (varint, omitted if None/0)."""
    b = b""
    if type_: b += b"\x08" + varint(type_)
    if param:  b += b"\x10" + varint(param)
    return base64.b64encode(b).decode()

ACTIONS = {
    "breakthrough": lambda a: pact(2),
    "ready":        lambda a: pact(3),
    "selecttalent": lambda a: pact(5, int(a[0])),
    "selectdaoyun": lambda a: pact(9, int(a[0])),
}

def main():
    action = sys.argv[1]
    b64 = ACTIONS[action](sys.argv[2:])
    print(f"{action} -> SimpleClientPact base64={b64}")
    session = frida.attach("YiXianPai.exe")
    sc = session.create_script(open(AG, encoding="utf-8").read())
    errs = []; sc.on("message", lambda m, d: errs.append(m) if m.get("type") == "error" else None)
    sc.load()
    print("sendmsg:", sc.exports_sync.sendmsg("SimpleClientPact", b64))
    for e in errs: print("ERR:", e.get("description"))
    session.detach()

if __name__ == "__main__":
    main()
