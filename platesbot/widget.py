"""HTML-виджет для сообщения в чате (Bot API 10.4, sendWidget).

Ограничения Telegram: до 32 КБ HTML и не более 4 КБ после zlib-сжатия,
только generic-шрифты, без внешних ресурсов, JS в песочнице QuickJS.
Состояние (последний номер, энергия) живёт в chat_data; бот обновляет его
через editMessageWidgetData, а по нажатию «Крутить» виджет шлёт request('roll').
"""
from __future__ import annotations

import json
import zlib

from core.rarity import format_price

WIDGET_HEIGHT = 330

HTML = r"""<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{margin:0;background:#0A0A0C}
#r{font-family:system-ui,sans-serif;background:#0A0A0C;color:#F2F3F5;border-radius:18px;padding:16px;min-height:330px;position:relative}
#glow{position:absolute;left:10%;right:10%;top:40px;height:120px;border-radius:50%;background:var(--g,transparent);opacity:.35;filter:blur(40px);transition:background .5s}
.hd{display:flex;justify-content:space-between;align-items:center;font-size:13px;color:#8B8F98;font-weight:600;position:relative}
.hd b{color:#F2F3F5;font-size:15px}
.en{color:#F2F3F5}
.pl{position:relative;margin:18px auto 0;width:100%;max-width:360px;height:78px;display:flex;background:#f4f4f0;color:#141414;border:3px solid #0f0f0f;border-radius:9px;font-family:ui-sans-serif,system-ui,sans-serif;font-weight:800;overflow:hidden;box-shadow:0 10px 24px -10px #000}
.pl.lit{box-shadow:0 10px 24px -10px #000,0 0 36px -4px var(--g,transparent)}
.mn{flex:1;display:flex;align-items:center;justify-content:center;gap:2px;font-size:42px;line-height:1;padding:0 6px}
.mn.s{font-size:30px}
.sl{display:inline-block;width:.56em;text-align:center;overflow:hidden;height:1em}
.sl i{display:block;font-style:normal;transition:transform .35s cubic-bezier(.2,1.3,.4,1)}
.sl.rl i{filter:blur(1px);opacity:.8}
.sm{font-size:36px}
.gp{width:8px}
.rg{width:25%;border-left:3px solid #0f0f0f;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:30px;gap:2px}
.rw{display:flex}
.rg small{font-size:9px;letter-spacing:.08em;display:flex;align-items:center;gap:4px}
.fl{display:inline-block;width:14px;height:9px;border:1px solid #0003;background:linear-gradient(#fff 33%,#0039a6 33% 66%,#d52b1e 66%)}
.st{position:relative;margin-top:14px;display:flex;justify-content:space-between;align-items:flex-end;min-height:48px}
.tier{display:inline-block;font-size:12px;font-weight:700;padding:5px 10px;border-radius:99px;background:#1E1F24;color:var(--g,#8B8F98)}
.pr{font-size:24px;font-weight:800;margin-top:6px;letter-spacing:-.02em}
.sub{color:#8B8F98;font-size:12px;text-align:right;max-width:46%}
.bt{display:flex;gap:8px;margin-top:14px;position:relative}
button{flex:1;height:46px;border:0;border-radius:13px;font:700 15px system-ui,sans-serif;background:#F2F3F5;color:#0B0C0F}
button.g{background:#1E1F24;color:#F2F3F5;flex:0 0 46%}
button:disabled{opacity:.6}
#msg{position:absolute;left:16px;right:16px;bottom:72px;text-align:center;font-size:12px;color:#8B8F98}
</style>
<div id="r"><div id="glow"></div>
<div class="hd"><b>Номера</b><span id="en" class="en"></span></div>
<div id="pl" class="pl"></div>
<div class="st"><div><span id="tier" class="tier"></span><div id="pr" class="pr"></div></div><div id="sub" class="sub"></div></div>
<div id="msg"></div>
<div class="bt"><button id="go">Крутить</button><button id="app" class="g">Приложение</button></div>
</div>
<script>
var W=TelegramWidget,S={},P={},busy=0,L="АВЕКМНОРСТУХ",D="0123456789";
function J(s){try{return JSON.parse(s||"{}")}catch(e){return{}}}
function g(i){return document.getElementById(i)}
function sl(t,c){var h="";for(var i=0;i<t.length;i++)h+=t[i]==" "?'<span class="gp"></span>':'<span class="sl'+(c?" "+c:"")+'" data-f="'+t[i]+'"><i>'+t[i]+'</i></span>';return h}
function draw(s){
 var pl=g("pl");
 if(!s.t){pl.innerHTML='<div class="mn s">Нажми «Крутить»</div>';g("tier").textContent="";g("pr").textContent="";g("sub").textContent="";return}
 if(s.c=="RU")pl.innerHTML='<div class="mn">'+sl(s.t[0],"sm")+'<span class="gp"></span>'+sl(s.t.slice(1,4))+'<span class="gp"></span>'+sl(s.t.slice(4),"sm")+'</div><div class="rg"><div class="rw">'+sl(s.r)+'</div><small>RUS <span class="fl"></span></small></div>';
 else pl.innerHTML='<div class="mn s">'+sl(s.x)+'</div>';
 document.getElementById("r").style.setProperty("--g",s.k||"transparent");
 pl.className="pl lit";g("tier").textContent=s.n||"";g("pr").textContent=s.p||"";
 g("sub").textContent=(s.g||"")+(s.q?" · топ "+s.q+"%":"");
 g("en").textContent=s.e?"Энергия "+s.e:"";
}
function roll(){
 if(busy||W.isPreview)return;busy=1;g("go").disabled=true;g("msg").textContent="";
 var sls=document.querySelectorAll(".sl"),t=setInterval(function(){for(var i=0;i<sls.length;i++){var a=D.indexOf(sls[i].getAttribute("data-f"))>=0?D:L;sls[i].className="sl rl";sls[i].firstChild.textContent=a[Math.floor(Math.random()*a.length)]}},70);
 W.request("roll").then(function(r){clearInterval(t);var d=J(r.result);if(d.err){draw(S);g("msg").textContent=d.err;busy=0;g("go").disabled=false;return}
  S=d;draw(d);var n=document.querySelectorAll(".sl");for(var i=0;i<n.length;i++)(function(e,i){e.className="sl rl";e.firstChild.style.transform="translateY(-110%)";setTimeout(function(){e.className="sl";e.firstChild.style.transform="";if(W.HapticFeedback)try{W.HapticFeedback.impactOccurred("light")}catch(x){}},120+i*90)})(n[i],i);
  setTimeout(function(){busy=0;g("go").disabled=false},200+n.length*90);
 }).catch(function(e){clearInterval(t);draw(S);busy=0;g("go").disabled=false;g("msg").textContent=(e&&e.message)=="NOT_ALLOWED"?"Открой бота и нажми /start":"Не вышло, попробуй ещё раз"})
}
S=J(W.chatData);P=J(W.publicData);draw(S);
g("go").onclick=roll;
g("app").onclick=function(){if(P.a)W.openTelegramLink(P.a)};
W.onEvent("chatDataChanged",function(){if(!busy){S=J(W.chatData);draw(S)}});
W.ready();
</script>"""


def widget_html() -> str:
    return HTML


def compressed_size(html: str) -> int:
    return len(zlib.compress(html.encode("utf-8"), 9))


def chat_data(roll: dict | None, energy: dict | None, country_name: str = "") -> str:
    """Состояние виджета (до 1024 байт)."""
    if not roll:
        d = {"e": f"{energy['current']}/{energy['max']}" if energy else ""}
        return json.dumps(d, ensure_ascii=False)
    plate, ev = roll["plate"], roll["eval"]
    from core.rarity import Evaluation
    price = format_price(Evaluation(**ev), plate["country"])
    d = {
        "c": plate["country"],
        "t": (plate["parts"]["l1"] + plate["parts"]["digits"] + plate["parts"]["l2"] + plate["parts"]["l3"]) if plate["country"] == "RU" else plate["text"],
        "r": plate["parts"].get("region", ""),
        "x": plate["text"],
        "n": ev["tier_name"], "k": ev["tier_color"], "p": price,
        "g": (country_name + (" · " + plate["region_name"] if plate.get("region_name") else ""))[:40],
        "q": ev["percentile"] if ev["percentile"] <= 50 else None,
        "s": ev["score"],
        "e": f"{energy['current']}/{energy['max']}" if energy else "",
    }
    return json.dumps({k: v for k, v in d.items() if v is not None}, ensure_ascii=False)


def public_data(bot_username: str, app_url: str) -> str:
    return json.dumps({"a": app_url or f"https://t.me/{bot_username}"}, ensure_ascii=False)
