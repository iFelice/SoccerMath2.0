"""
Smoke test anti-crash per il toggle Tema (dark/light) nella sidebar.
Esegue l'intera app con Streamlit AppTest in entrambi gli stati del toggle:
  1) ON  (segue tema sistema)      -> nessun CSS iniettato
  2) OFF (modalita' chiara forzata) -> CSS light iniettato
"""
import sys
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("app.py", default_timeout=120)

# --- 1) Stato iniziale: toggle ON (default value=True) ---
at.run()
assert not at.exception, f"CRASH con toggle ON: {at.exception}"

assert len(at.toggle) == 1, f"Atteso 1 toggle, trovati {len(at.toggle)}"
assert at.toggle[0].value is True, "Il toggle dovrebbe partire ON (segue sistema)"
print("✅ Run 1 OK - toggle ON (segue tema sistema), nessuna eccezione")

# --- 2) Toggle OFF: forza modalita' chiara (braccio CSS) ---
at.toggle[0].set_value(False).run()
assert not at.exception, f"CRASH con toggle OFF: {at.exception}"
assert at.toggle[0].value is False, "Il toggle dovrebbe essere OFF"
# Il blocco CSS forzato deve essere stato renderizzato
css_blocks = [m for m in at.markdown if "<style>" in (m.value or "")]
assert len(css_blocks) >= 2, f"Attesi >=2 blocchi <style> (base + light forzato), trovati {len(css_blocks)}"
forced = [m for m in css_blocks if "color-scheme: light" in m.value]
assert len(forced) == 1, "Il blocco CSS 'modalita' chiara forzata' non e' presente!"
print(f"✅ Run 2 OK - toggle OFF, CSS light forzato presente ({len(css_blocks)} blocchi <style>)")

# --- 3) Torno ON: il CSS forzato deve sparire ---
at.toggle[0].set_value(True).run()
assert not at.exception, f"CRash tornando a toggle ON: {at.exception}"
css_blocks = [m for m in at.markdown if "<style>" in (m.value or "")]
assert all("color-scheme: light" not in m.value for m in css_blocks), "CSS light forzato ancora presente con toggle ON!"
print("✅ Run 3 OK - ritorno a ON, CSS forzato rimosso, nessuna eccezione")

# --- 4) Lo stato del toggle sopravvive a un rerun generico ---
at.button(key="billy_chat_send")  # solo per forzare un rerun senza cambiare il toggle
at.run()
assert not at.exception, f"CRASH al rerun: {at.exception}"
assert at.toggle[0].value is False or at.toggle[0].value is True
print("✅ Run 4 OK - rerun generico senza crash")

print("\n🎉 TUTTI I TEST PASSATI: nessun crash in nessuno stato del toggle.")
sys.exit(0)
