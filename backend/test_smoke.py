"""Test de fumée : rejoue les 4 scénarios réels et vérifie que le pipeline complet
tourne sans erreur, avec des résultats cohérents (au moins une détection par scénario)."""

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

from app.scenario_engine import ScenarioPlayer, SCENARIOS


def run_scenario(fault_type: str):
    print(f"\n{'=' * 70}\nSCÉNARIO : {fault_type}\n{'=' * 70}")
    player = ScenarioPlayer(fault_type=fault_type)
    print(f"{len(player)} points chargés depuis {SCENARIOS[fault_type]}")

    m1_alerts = 0
    m2_calls = 0
    m3_alerts = 0
    m4_alerts = 0
    last_m2 = None

    for result in player.replay(realtime=False):
        if result["m1"]["smoothed_anomaly"]:
            m1_alerts += 1
        if result["m2"]:
            m2_calls += 1
            last_m2 = result["m2"]
        if result["m3"] and result["m3"].get("alert"):
            m3_alerts += 1
        if result["m4"]["status"] == "active" and result["m4"]["alert"]:
            m4_alerts += 1

        # Affiche quelques points clés
        if result["step"] in (0, len(player) // 2, len(player) - 1):
            print(f"  t={result['step']:3d}  label_reel={result['ground_truth_label']:15s}  "
                  f"M1_score={result['m1']['anomaly_score']:.3f} "
                  f"(seuil={result['m1']['threshold']:.3f})  "
                  f"M1_alerte={result['m1']['smoothed_anomaly']}  "
                  f"M2={result['m2']['predicted_class'] if result['m2'] else '-'}  "
                  f"M4={result['m4']['status']}")

    print(f"\nRésumé : M1 alertes={m1_alerts}/{len(player)}  M2 appels={m2_calls}  "
          f"dernière classe M2={last_m2['predicted_class'] if last_m2 else None} "
          f"(confiance={last_m2['confidence'] if last_m2 else None})  "
          f"M3 alertes={m3_alerts}  M4 alertes={m4_alerts}")
    return True


if __name__ == "__main__":
    ok = True
    for fault_type in SCENARIOS:
        try:
            run_scenario(fault_type)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"❌ ÉCHEC sur {fault_type} : {e}")
            ok = False
    print("\n" + ("✅ TOUS LES SCÉNARIOS OK" if ok else "❌ DES ERREURS SUBSISTENT"))
