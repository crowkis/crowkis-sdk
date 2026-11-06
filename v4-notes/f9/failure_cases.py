import os, subprocess, time, sys
from crowkis import voice_session
TOK=os.environ["CROWKIS_AUTH_TOKEN"]; kw=dict(host="127.0.0.1",port=7393,tenant="voice")
def dk(*a): subprocess.run(["docker",*a,"crowkis-f9"],capture_output=True)
def turn(s,q,a="Our store opens at nine in the morning and closes at six in the evening every day."):
    t=time.perf_counter()
    try:
        d=s.decide(q); r=s.record(d,a) if d.needs_model else None
        return f"ok {d.action if hasattr(d,'action') else ''} needs_model={d.needs_model} {round((time.perf_counter()-t)*1000)}ms stored={getattr(r,'stored',None)}"
    except Exception as e: return f"RAISED {type(e).__name__}: {str(e)[:80]}"
print("1 wrong token:", turn(voice_session(auth_token="wrong-token",**kw),"What time do you open on weekdays?"))
s=voice_session(auth_token=TOK,**kw)
print("2a up:", turn(s,"What time do you close on weekends?"))
dk("stop"); print("2b stopped:", turn(s,"Do you have parking at the store?")); print("2b stopped (new session):", turn(voice_session(auth_token=TOK,**kw),"Is there a cafe nearby the store?"))
dk("start"); time.sleep(8)
print("2c restarted, same session:", turn(s,"Do you sell gift cards at the store?")); print("2c restarted, new session:", turn(voice_session(auth_token=TOK,**kw),"Can I return a gift card at the store?"))
dk("pause"); print("3 hung server (paused):", turn(voice_session(auth_token=TOK,**kw),"Do you offer free wifi at the store?")); dk("unpause")
time.sleep(2); print("3b after unpause:", turn(voice_session(auth_token=TOK,**kw),"Do you offer student discounts at the store?"))
print("stats:", {k:v for k,v in s.stats().items() if 'fail' in k or 'slow' in k or 'error' in k or 'timeout' in k} if hasattr(s,'stats') else '')
