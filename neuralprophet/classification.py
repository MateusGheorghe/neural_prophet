import time
from collections import OrderedDict
import numpy as np
import pandas as pd
from neuralprophet.forecaster import NeuralProphet
import torch
from torch.utils.data import DataLoader
import logging
from tqdm import tqdm

from neuralprophet import configure
from neuralprophet import time_net
from neuralprophet import time_dataset
from neuralprophet import df_utils
from neuralprophet import utils
from neuralprophet.plot_forecast import plot, plot_components
from neuralprophet.plot_model_parameters import plot_parameters
from neuralprophet import metrics
from neuralprophet.df_utils import get_max_num_lags

from neuralprophet.utils import set_logger_level


log = logging.getLogger("NP.forecaster")


class Classification_NP(NeuralProphet):
    """NeuralProphet binary classifier.
    A simple classifier for binary classes time-series.

    Parameters
    ----------
    Similar to the NeuralProphet forecaster.

    AR Config
    n_lags : int
        Previous time series steps to include in auto-regression. Aka AR-order
    Note
    ----
        One can notice that n_lags is set to 0 because y is the output column. A lagged regressor is required so the classification
    can be accomplished. You should not set it to a different value, as using auto-regression for classification would mean training the model with its labels.

    Different default:
    loss_func : str, torch.nn.functional.loss
            Type of loss to use:

            Options
                * (default) ``bce``: Binary Cross-Entropy
    Note
    ----
                Notice that a sigmoid is attached to the output layer for the binary classification models. Therefore, you should use loss functions that account for this detail.

    """

    def __init__(self, loss_func="bce", *args, **kwargs):
        super(Classification_NP, self).__init__(*args, **kwargs)

        kwargs = self.forecaster_locals
        kwargs["loss_func"] = loss_func
        self.classification_task = True
        collect_metrics = kwargs["collect_metrics"]

        METRICS = {
            "acc": metrics.Accuracy,
            "bal_acc": metrics.Balanced_Accuracy,
            "f1": metrics.F1Score,
        }
        # General
        self.name = "NeuralProphetBinaryClassifier"
        self.config_train = configure.from_kwargs(configure.Train, kwargs)
        # self.config_train = loss_func
        # self.config_train.loss_func_name = loss_func
        if collect_metrics is None:
            collect_metrics = []
        elif collect_metrics is True:
            collect_metrics = ["acc", "bal_acc", "f1"]
        elif isinstance(collect_metrics, str):
            if not collect_metrics.lower() in METRICS.keys():
                raise ValueError("Received unsupported argument for collect_metrics.")
            collect_metrics = [collect_metrics]
        elif isinstance(collect_metrics, list):
            if not all([m.lower() in METRICS.keys() for m in collect_metrics]):
                raise ValueError("Received unsupported argument for collect_metrics.")
        elif collect_metrics is not False:
            raise ValueError("Received unsupported argument for collect_metrics.")

        self.metrics = None
        if isinstance(collect_metrics, list):
            self.metrics = metrics.MetricsCollection(
                metrics=[metrics.LossMetric(self.config_train.loss_func)]
                + [METRICS[m.lower()]() for m in collect_metrics],
                value_metrics=[metrics.ValueMetric("Loss")],
            )

    def fit(
        self,
        df,
        freq="auto",
        validation_df=None,
        progress="bar",
        minimal=False,
    ):
        max_lags = get_max_num_lags(self.config_covar, self.n_lags)
        if self.n_lags > 0:
            log.warning(
                "Warning! Auto-regression is activated, the model is using the classifier label as input. Please consider setting n_lags=0."
            )
        if max_lags == 0:
            log.warning("Warning! Please add lagged regressor as the input of the classifier")
        if self.config_train.loss_func_name.lower() in ["bce", "bceloss"]:
            log.info("Classification with bce loss")
        else:
            raise NotImplementedError(
                "Currently NeuralProphet Classification module does not support {} loss function. Please, set loss function to 'bce' ".format(
                    self.config_train.loss_func_name
                )
            )
        return super().fit(
            df,
            freq=freq,
            validation_df=validation_df,
            progress=progress,
            minimal=minimal,
        )

    def predict(self, df):
        df = super().predict(df)
        # create a line for each forecast_lag
        # 'yhat<i>' is the forecast for 'y' at 'ds' from i steps ago (value between 0 and 1).
        df, received_ID_col, received_single_time_series, received_dict = df_utils.prep_or_copy_df(df)
        df_pred = pd.DataFrame()
        for df_name, df_i in df.groupby("ID"):
            for i in range(self.n_forecasts):
                df_i = df_i.rename(columns={"yhat{}".format(i + 1): "yhat_raw{}".format(i + 1)}).copy(deep=True)
                yhat = df_i["yhat_raw{}".format(i + 1)]
                yhat = np.array(yhat.values, dtype=np.float64)
                df_i["yhat{}".format(i + 1)] = yhat.round()
                df_i["residual{}".format(i + 1)] = df_i["yhat_raw{}".format(i + 1)] - df_i["y"]
                df_i["ID"] = df_name
                df_pred = pd.concat((df_pred, df_i), ignore_index=True)
        df = df_utils.return_df_in_original_format(df_pred, received_ID_col, received_single_time_series, received_dict)
        return df