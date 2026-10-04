"""
M4 — Seuils dynamiques (ARIMA, fenêtre glissante)

Reproduit exactement le moteur de 07_demo_live : à chaque nouveau point, on ré-ajuste un
ARIMA sur les WINDOW dernières minutes connues (hors point courant), on prédit ce point
"en avant" (vraie prédiction hors échantillon), et on compare à la valeur réellement
observée. Hors de l'intervalle de confiance à 95% -> alerte.

Contrairement à M1/M2/M3, ce n'est pas un modèle chargé depuis un artefact figé : le
modèle ARIMA est ré-entraîné à la volée sur la fenêtre courante à chaque appel (c'est
le principe même du "seuil dynamique" -- pas de seuil fixe appris une fois pour toutes).
C'est volontairement plus coûteux en calcul qu'une simple règle, mais c'est justement ce
qui permet au seuil de suivre une montée de charge légitime sans fausse alerte.
"""

import warnings

import math
import numpy as np
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tools.sm_exceptions import ConvergenceWarning

WINDOW = 15
SIMPLE_ORDERS = [(1, 0, 0), (1, 1, 0), (0, 1, 1), (2, 1, 0)]

# Seuil fixe "classique" utilisé uniquement pour la comparaison affichée à côté du
# verdict de M4 (ex: "alerte si CPU > 80%") -- jamais utilisé pour la décision elle-même,
# juste pour montrer concrètement, point par point, ce qu'un monitoring basique aurait
# dit à la place du seuil dynamique.
FIXED_THRESHOLD_PCT = 80.0


def _fit_best_arima(y):
    best = None
    for order in SIMPLE_ORDERS:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                model = ARIMA(y, order=order).fit(method_kwargs={"maxiter": 200})
            except Exception:
                continue
            converged = not any(issubclass(w.category, ConvergenceWarning) for w in caught)
        candidate = {"model": model, "order": order, "aic": model.aic, "converged": converged}
        if best is None or (candidate["converged"], -candidate["aic"]) > (best["converged"], -best["aic"]):
            best = candidate
    return best


def predict(metric_history: list[float], metric_name: str = "cpu_usage_pct") -> dict:
    """
    metric_history : valeurs passées de la métrique pour CE service, dans l'ordre chronologique,
                      SANS inclure le tout dernier point à évaluer (c'est celui qu'on compare
                      à la prédiction). Longueur attendue >= WINDOW + 1.
    """
    # En JSON (flux live réel), une métrique manquante arrive en None ; un CSV relu
    # par pandas la représente en NaN. On aligne les deux -- même comportement, que
    # les données viennent d'un rejeu ou du cluster réel.
    metric_history = [float("nan") if v is None else float(v) for v in metric_history]

    actual_now = metric_history[-1] if metric_history else None
    if actual_now is not None and math.isnan(actual_now):
        # Vrai cas réel : scrape Prometheus raté pour ce pod à ce tick précis (souvent
        # juste après un restart). On ne fait PAS semblant que 0% ou la dernière valeur
        # connue est la réalité -- on dit explicitement qu'on ne sait pas.
        return {
            "model": "M4",
            "metric": metric_name,
            "status": "missing_data",
            "message": "Métrique manquante pour ce point (scrape raté) — pas de verdict.",
            "alert": False,
            "fixed_threshold_pct": FIXED_THRESHOLD_PCT,
            "fixed_alert": False,
        }
    fixed_alert = actual_now is not None and actual_now > FIXED_THRESHOLD_PCT

    if len(metric_history) < WINDOW + 1:
        return {
            "model": "M4",
            "metric": metric_name,
            "status": "warmup",
            "message": f"Historique insuffisant ({len(metric_history)}/{WINDOW + 1} points) — seuil dynamique pas encore actif",
            "alert": False,
            # Le seuil fixe, lui, n'a besoin d'aucun historique -- il peut juger dès le
            # premier point. C'est un vrai avantage du seuil fixe qu'il faut reconnaître :
            # M4 met ~15 points à "chauffer" avant de devenir utile.
            "fixed_threshold_pct": FIXED_THRESHOLD_PCT,
            "fixed_alert": fixed_alert,
        }

    hist = np.array(metric_history[-(WINDOW + 1):-1])
    actual = metric_history[-1]

    best = _fit_best_arima(hist)
    if best is None:
        return {
            "model": "M4", "metric": metric_name, "status": "fit_failed",
            "actual": actual, "alert": False,
            "fixed_threshold_pct": FIXED_THRESHOLD_PCT, "fixed_alert": fixed_alert,
        }

    fc = best["model"].get_forecast(steps=1)
    frame = fc.summary_frame(alpha=0.05)
    lower, upper, forecast = (
        float(frame["mean_ci_lower"].iloc[0]),
        float(frame["mean_ci_upper"].iloc[0]),
        float(frame["mean"].iloc[0]),
    )
    alert = not (lower <= actual <= upper)
    half_width = max((upper - lower) / 2, 1e-6)
    deviation_sigma = round((actual - forecast) / (half_width / 1.96), 2)

    return {
        "model": "M4",
        "metric": metric_name,
        "status": "active",
        "actual": round(float(actual), 2),
        "forecast": round(forecast, 2),
        "dynamic_threshold_lower": round(lower, 2),
        "dynamic_threshold_upper": round(upper, 2),
        "arima_order": best["order"],
        "alert": bool(alert),
        "deviation_sigma": deviation_sigma,
        # Comparaison affichée à côté du verdict de M4 -- pas utilisée pour décider,
        # juste pour montrer, point par point, ce qu'un seuil fixe classique aurait dit.
        "fixed_threshold_pct": FIXED_THRESHOLD_PCT,
        "fixed_alert": fixed_alert,
        "avoided_false_alarm": bool(fixed_alert and not alert),
        "missed_by_fixed": bool(alert and not fixed_alert),
    }
