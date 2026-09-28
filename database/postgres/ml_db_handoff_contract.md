# ML → Database Handoff Contract V1

## Purpose

Define the contract between the ML team and the PostgreSQL serving layer.

The ML team is responsible for:
- feature experimentation
- model training
- model evaluation
- SHAP/explainability generation
- model artifact creation

The Database/Backend layer is responsible for:
- registering model metadata
- storing prediction outputs
- storing risk flags
- storing forecast payloads
- preserving prediction history
- serving predictions through PostgreSQL/API

---

## 1. Model Artifact

For every deployable model, ML provides:

- model_name
- model_version
- model_type
- target_name
- feature_version
- gold_version
- training period
- validation period
- test period
- evaluation metrics
- hyperparameters
- model artifact path

Example:

```json
{
  "model_name": "project_deterioration_model",
  "model_version": "xgb_v1",
  "model_type": "XGBoost",
  "target_name": "target_6m",
  "feature_version": "gold_ml_v1",
  "gold_version": "features_v1"
}