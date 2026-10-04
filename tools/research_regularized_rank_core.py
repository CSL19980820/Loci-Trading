"""A single frozen, date-weighted ridge model for isolated return research.

This module does not choose strategy features, simulate orders, tune parameters,
or mutate production. Labels are order-opportunity net returns in percent.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

RIDGE_LAMBDA = 1.0
Z_LIMIT = 5.0
MIN_TRAIN_ROWS = 100
MIN_TRAIN_DAYS = 60
MIN_TRAIN_MONTHS = 6
STATUSES = {"closed", "cancelled", "unresolved"}


def feature_complete(frame: pd.DataFrame, features: list[str]) -> pd.Series:
    if not features or len(features) > 12 or len(set(features)) != len(features):
        raise ValueError("Use one fixed list of 1..12 distinct features")
    values = frame[features].apply(pd.to_numeric, errors="coerce")
    return pd.Series(np.isfinite(values.to_numpy()).all(axis=1), index=frame.index)


def _dates(values: pd.Series, *, allow_empty: bool) -> pd.Series:
    text = values.astype("string")
    empty = text.isna() | text.eq("")
    parsed = pd.to_datetime(text.mask(empty), format="%Y-%m-%d", errors="raise")
    if not allow_empty and parsed.isna().any():
        raise ValueError("Decision dates must be known")
    return parsed.dt.strftime("%Y-%m-%d").astype("string")


def _solve(x: np.ndarray, y: np.ndarray, decision_dates: pd.Series) -> dict[str, Any]:
    # Each observed, usable training date receives equal total weight. Empty
    # market days belong in evaluation budgets, not as invented training labels.
    counts = decision_dates.value_counts()
    weights = decision_dates.map(lambda day: 1.0 / counts[day]).to_numpy(dtype=float)
    weights = weights / weights.sum()
    mean = weights @ x
    variance = weights @ np.square(x - mean)
    scale = np.sqrt(np.maximum(variance, 0.0))
    constant = scale <= 1e-12
    scale[constant] = 1.0
    z = np.clip((x - mean) / scale, -Z_LIMIT, Z_LIMIT)
    # Clipping can change the weighted mean. Recenter AFTER clipping so that
    # the intercept is truly unpenalized in the declared objective.
    z_mean = weights @ z
    y_mean = float(weights @ y)
    design = z - z_mean
    target = y - y_mean
    lhs = design.T @ (weights[:, None] * design) + RIDGE_LAMBDA * np.eye(x.shape[1])
    rhs = design.T @ (weights * target)
    coefficients = np.linalg.solve(lhs, rhs)
    intercept = y_mean - float(z_mean @ coefficients)
    prediction = intercept + z @ coefficients
    error = float(weights @ np.square(y - prediction))
    penalty = float(RIDGE_LAMBDA * coefficients @ coefficients)
    return {
        "mean": mean.tolist(), "scale": scale.tolist(),
        "constant_features": constant.tolist(), "clipped_weighted_mean": z_mean.tolist(),
        "coefficients": coefficients.tolist(), "intercept": intercept,
        "weighted_label_mean": y_mean, "weighted_training_mse": error,
        "penalty": penalty, "objective_value": error + penalty,
        "date_weight_min": float(pd.Series(weights).groupby(decision_dates.reset_index(drop=True)).sum().min()),
        "date_weight_max": float(pd.Series(weights).groupby(decision_dates.reset_index(drop=True)).sum().max()),
    }


def fit_ridge(
    frame: pd.DataFrame, features: list[str], *, fit_end: str, validation_start: str,
    fit_start: str = "2024-01-01",
) -> dict[str, Any]:
    """Fit only complete features with labels actually available by fit_end.

    Required fields: code, decision_date, label_available_date, label_status,
    net_return_pct and all features. A resolved cancellation has zero return and
    becomes available when cancellation is known. Unresolved labels never fit.
    """
    fit_start = str(pd.Timestamp(fit_start).date())
    fit_end = str(pd.Timestamp(fit_end).date())
    validation_start = str(pd.Timestamp(validation_start).date())
    if fit_start > fit_end or fit_end >= validation_start:
        raise ValueError("Fit cutoff must precede validation start")
    required = {"code", "decision_date", "label_available_date", "label_status", "net_return_pct"}
    if required - set(frame):
        raise ValueError(f"Missing label contract fields: {sorted(required - set(frame))}")
    decision = _dates(frame["decision_date"], allow_empty=False)
    available = _dates(frame["label_available_date"], allow_empty=True)
    status = frame["label_status"].astype(str)
    if not set(status).issubset(STATUSES):
        raise ValueError("Unknown label status")
    if frame.assign(_decision=decision).duplicated(["_decision", "code"]).any():
        raise ValueError("Duplicate decision-date/code label rows")
    if (available.notna() & available.lt(decision)).any():
        raise ValueError("Label cannot precede its decision")
    resolved = status.isin(["closed", "cancelled"])
    if (resolved & available.isna()).any():
        raise ValueError("Resolved labels require an availability date")
    complete = feature_complete(frame, features)
    known = resolved & available.le(fit_end).fillna(False) & decision.between(fit_start, fit_end)
    eligible = known & complete
    train = frame.loc[eligible]
    dates = decision.loc[eligible]
    labels = pd.to_numeric(train["net_return_pct"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(labels).all():
        raise ValueError("An available training label is missing or non-finite")
    if not np.equal(labels[status.loc[eligible].eq("cancelled").to_numpy()], 0).all():
        raise ValueError("Resolved unfilled orders have exactly zero opportunity return")
    months = dates.str.slice(0, 7).nunique()
    if len(train) < MIN_TRAIN_ROWS or dates.nunique() < MIN_TRAIN_DAYS or months < MIN_TRAIN_MONTHS:
        raise ValueError("Insufficient training information: need100 labels,60 dates,6 months")
    if not available.loc[eligible].lt(validation_start).all():
        raise AssertionError("Training label overlaps validation information time")
    x = train[features].to_numpy(dtype=float)
    solution = _solve(x, labels, dates)
    if not all(np.isfinite(solution[key]).all() for key in ("mean", "scale", "coefficients")):
        raise AssertionError("Non-finite fitted model")
    return {
        "version": "date_weighted_ridge_v1", "features": features,
        "fit_start": fit_start, "fit_end": fit_end, "validation_start": validation_start,
        "target": "resolved order opportunity net return in percentage points",
        "objective": "sum(w_i*(y_i-intercept-z_i@coef)^2)+lambda*sum(coef^2); sum(w)=1",
        "ridge_lambda": RIDGE_LAMBDA, "z_limit": Z_LIMIT,
        "training_rows": len(train), "training_dates": int(dates.nunique()),
        "training_months": int(months), "max_label_available_date": str(available.loc[eligible].max()),
        "training_decision_start": str(dates.min()), "training_decision_end": str(dates.max()),
        "closed_labels": int(status.loc[eligible].eq("closed").sum()),
        "cancelled_zero_labels": int(status.loc[eligible].eq("cancelled").sum()),
        "outside_window_or_unavailable_rows": int((~known).sum()),
        "known_but_incomplete_features": int((known & ~complete).sum()),
        **solution,
    }


def predict_ridge(model: dict[str, Any], frame: pd.DataFrame) -> pd.Series:
    if model["version"] != "date_weighted_ridge_v1" or model["ridge_lambda"] != RIDGE_LAMBDA:
        raise ValueError("Unexpected frozen model")
    features = list(model["features"])
    eligible = feature_complete(frame, features)
    result = pd.Series(np.nan, index=frame.index, name="predicted_net_pct", dtype=float)
    x = frame.loc[eligible, features].to_numpy(dtype=float)
    z = np.clip((x - np.array(model["mean"])) / np.array(model["scale"]), -Z_LIMIT, Z_LIMIT)
    result.loc[eligible] = model["intercept"] + z @ np.array(model["coefficients"])
    return result


def self_check() -> dict[str, Any]:
    dates = pd.bdate_range("2024-01-02", "2024-11-29")
    x = np.linspace(-2., 2., len(dates))
    frame = pd.DataFrame({
        "code": "600001", "decision_date": dates.strftime("%Y-%m-%d"),
        "label_available_date": (dates + pd.offsets.BDay(3)).strftime("%Y-%m-%d"),
        "label_status": "closed", "net_return_pct": 1. + 2*x, "shape": x,
    })
    kwargs = dict(fit_end="2024-12-31", validation_start="2025-01-01")
    model = fit_ridge(frame, ["shape"], **kwargs)
    unit = np.linspace(-2., 2., len(dates))
    # With one standardized un-clipped feature, lambda1 halves the OLS slope.
    assert np.isclose(model["coefficients"][0], unit.std(), atol=1e-12)
    assert np.isclose(model["intercept"], 1., atol=1e-12)
    future = frame.iloc[:2].copy()
    future["code"] = ["600002", "600003"]
    future["label_available_date"] = "2025-01-02"
    future["net_return_pct"] = [1e8, -1e8]
    future["shape"] = [1e9, -1e9]
    appended = fit_ridge(pd.concat([frame, future], ignore_index=True), ["shape"], **kwargs)
    assert appended["coefficients"] == model["coefficients"]
    assert appended["mean"] == model["mean"]
    assert appended["intercept"] == model["intercept"]
    before = frame.iloc[:1].copy()
    before["decision_date"], before["label_available_date"] = "2023-11-01", "2023-11-06"
    before["shape"], before["net_return_pct"] = 1e8, 1e8
    prewindow = fit_ridge(pd.concat([before, frame], ignore_index=True), ["shape"], **kwargs)
    assert prewindow["coefficients"] == model["coefficients"]
    assert prewindow["intercept"] == model["intercept"]
    duplicate = frame.copy()
    duplicate["code"] = "600002"
    duplicated_day = pd.concat([frame, duplicate.iloc[:12]], ignore_index=True)
    replicated = fit_ridge(duplicated_day, ["shape"], **kwargs)
    assert np.allclose(replicated["coefficients"], model["coefficients"], atol=1e-12)
    assert np.isclose(replicated["date_weight_min"], replicated["date_weight_max"], atol=1e-15)
    shifted = frame.copy()
    shifted["shape"] = frame["shape"]*100 + 300
    rescaled = fit_ridge(shifted, ["shape"], **kwargs)
    assert np.allclose(predict_ridge(model, frame), predict_ridge(rescaled, shifted), atol=1e-12)
    extreme = pd.DataFrame({"shape": [-1e30, 1e30, np.nan]})
    predictions = predict_ridge(model, extreme)
    assert np.isclose(predictions.iloc[0], model["intercept"]-Z_LIMIT*model["coefficients"][0])
    assert np.isclose(predictions.iloc[1], model["intercept"]+Z_LIMIT*model["coefficients"][0])
    assert pd.isna(predictions.iloc[2])
    cancelled = frame.copy()
    cancelled.loc[0, ["label_status", "net_return_pct"]] = ["cancelled", 0.]
    assert fit_ridge(cancelled, ["shape"], **kwargs)["cancelled_zero_labels"] == 1
    cancelled.loc[0, "label_available_date"] = "2025-01-03"
    assert fit_ridge(cancelled, ["shape"], **kwargs)["cancelled_zero_labels"] == 0
    clipped = frame.copy()
    clipped.loc[0, "shape"] = 1e6
    fitted = fit_ridge(clipped, ["shape"], **kwargs)
    prediction = predict_ridge(fitted, clipped)
    assert abs(float((clipped.net_return_pct-prediction).mean())) < 1e-12
    constant = frame.assign(shape=9., net_return_pct=3.)
    constant_model = fit_ridge(constant, ["shape"], **kwargs)
    assert np.allclose(constant_model["coefficients"], 0., atol=1e-12)
    assert np.allclose(predict_ridge(constant_model, constant), 3.)
    return {"status": "passed", "checks": [
        "declared_lambda_objective", "future_labels_and_features_do_not_fit", "prewindow_labels_do_not_fit",
        "equal_date_weights_not_equal_row_weights", "feature_unit_invariance",
        "prediction_uses_past_scaler_and_fixed_clip", "missing_prediction_feature_stays_unknown",
        "resolved_cancel_zero_has_its_own_information_time", "clipped_design_unpenalized_intercept",
        "constant_feature_and_target",
    ]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = self_check()
    encoded = json.dumps(result, ensure_ascii=False, indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
