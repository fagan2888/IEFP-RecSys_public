import luigi
import pandas as pd
import yaml

from datetime import datetime
from sklearn.base import BaseEstimator

from iefp.data import s3
from iefp.data.postgres import (
    get_db_engine,
    get_model_info_by_path,
    write_recommendation_eval,
)
from iefp.modelling import EvaluateGradientBoosting, TrainGradientBoosting
from iefp.modelling import EvaluateLogisticRegression, TrainLogisticRegression
from iefp.modelling import EvaluateRandomForest, TrainRandomForest
from iefp.recommendation import get_top_recommendations


class EvaluateRecommendationsGB(luigi.Task):
    date = luigi.DateSecondParameter(default=datetime.now())
    task_complete = False

    def requires(self):
        return [TrainGradientBoosting(self.date), EvaluateGradientBoosting(self.date)]

    def run(self):
        params = yaml.load(open("./conf/base/parameters.yml"), Loader=yaml.FullLoader)[
            "evaluation_params"
        ]

        model = s3.read_pickle(self.input()[0].path)
        model_id, test_path, train_path = get_model_info_by_path(self.input()[0].path)

        df_train = s3.read_parquet(train_path)
        df_test = s3.read_parquet(test_path)

        rec_error = get_aggregate_recommendation_error(
            df_train,
            df_test,
            model,
            params["set_size"],
            params["num_recs"],
            params["percent_sample"],
        )
        write_recommendation_eval(get_db_engine(), rec_error, model_id, params)
        self.task_complete = True

    def complete(self):
        return self.task_complete


class EvaluateRecommendationsLG(luigi.Task):
    date = luigi.DateSecondParameter(default=datetime.now())
    task_complete = False

    def requires(self):
        return [
            TrainLogisticRegression(self.date),
            EvaluateLogisticRegression(self.date),
        ]

    def run(self):
        params = yaml.load(open("./conf/base/parameters.yml"), Loader=yaml.FullLoader)[
            "evaluation_params"
        ]

        model = s3.read_pickle(self.input()[0].path)
        model_id, test_path, train_path = get_model_info_by_path(self.input()[0].path)

        df_train = s3.read_parquet(train_path)
        df_test = s3.read_parquet(test_path)

        rec_error = get_aggregate_recommendation_error(
            df_train,
            df_test,
            model,
            params["set_size"],
            params["num_recs"],
            params["percent_sample"],
        )

        write_recommendation_eval(get_db_engine(), rec_error, model_id, params)
        self.task_complete = True

    def complete(self):
        return self.task_complete


class EvaluateRecommendationsRF(luigi.Task):
    date = luigi.DateSecondParameter(default=datetime.now())
    task_complete = False

    def requires(self):
        return [TrainRandomForest(self.date), EvaluateRandomForest(self.date)]

    def run(self):
        params = yaml.load(open("./conf/base/parameters.yml"), Loader=yaml.FullLoader)[
            "evaluation_params"
        ]

        model = s3.read_pickle(self.input()[0].path)
        model_id, test_path, train_path = get_model_info_by_path(self.input()[0].path)

        df_train = s3.read_parquet(train_path)
        df_test = s3.read_parquet(test_path)

        rec_error = get_aggregate_recommendation_error(
            df_train,
            df_test,
            model,
            params["set_size"],
            params["num_recs"],
            params["percent_sample"],
        )

        write_recommendation_eval(get_db_engine(), rec_error, model_id, params)
        self.task_complete = True

    def complete(self):
        return self.task_complete


def get_sub_group(df: pd.DataFrame, observation: pd.Series):
    """
    Selects a subgroup of the population (full dataset) which matches the
    demographic profile of the individual observation

    :param df: Full journey dataset
    :param observation: Specific journey
    :return dataframe: Subgroup dataframe
    """

    journey = pd.DataFrame(observation).T

    # Create "age bracket" features for journey and full dataset df
    journey["youngest"] = (journey["d_age"] >= 0.0) & (journey["d_age"] < 0.2)
    journey["young_adult"] = (journey["d_age"] >= 0.2) & (journey["d_age"] < 0.3)
    journey["adult"] = (journey["d_age"] >= 0.3) & (journey["d_age"] < 0.40)
    journey["middle_adult"] = (journey["d_age"] >= 0.4) & (journey["d_age"] < 0.5)
    journey["older_adult"] = (journey["d_age"] >= 0.5) & (journey["d_age"] < 0.6)
    journey["senior"] = (journey["d_age"] >= 0.6) & (journey["d_age"] < 0.7)
    journey["old_senior"] = (journey["d_age"] >= 0.7) & (journey["d_age"] < 0.8)
    journey["old"] = journey["d_age"] >= 0.8

    df["youngest"] = (df["d_age"] >= 0.0) & (df["d_age"] < 0.2)
    df["young_adult"] = (df["d_age"] >= 0.2) & (df["d_age"] < 0.3)
    df["adult"] = (df["d_age"] >= 0.3) & (df["d_age"] < 0.40)
    df["middle_adult"] = (df["d_age"] >= 0.4) & (df["d_age"] < 0.5)
    df["older_adult"] = (df["d_age"] >= 0.5) & (df["d_age"] < 0.6)
    df["senior"] = (df["d_age"] >= 0.6) & (df["d_age"] < 0.7)
    df["old_senior"] = (df["d_age"] >= 0.7) & (df["d_age"] < 0.8)
    df["old"] = df["d_age"] >= 0.8

    # Select filtering demographic features
    dems = [
        "d_gender_M",
        "d_disabled",
        "d_subsidy",
        "d_rsi_True",
        "youngest",
        "young_adult",
        "adult",
        "middle_adult",
        "older_adult",
        "senior",
        "old_senior",
        "old",
        "d_nationality_other",
        "d_school_qualification_1.0",
        "d_school_qualification_2.0",
        "d_school_qualification_3.0",
        "d_school_qualification_4.0",
        "d_school_qualification_5.0",
        "d_school_qualification_6.0"
    ]

    sub_group = df.merge(journey[dems], on=dems, right_index=True, how="inner")

    return sub_group


def eval_recommendations(
    journey: pd.Series, df_full: pd.DataFrame, recommendations_list: list()
):
    """
    Evaluates recommended interventions for a journey/individual by
    comparing the predicted probability of success, given a set of interventions,
    with the average mean success rate found in ground truth data among
    a similar subgroup

    :param journey: Individual journey as pandas Series
    :param full_dataset: Full journey dataset
    :param recommendation_lst: List of recommendationed interventions
    :return error: Average error for individual journey
    """

    if not recommendations_list:
        return 1

    predicted_prob_success = recommendations_list.pop()

    sub_group = get_sub_group(df_full, journey)

    recommendations = [
        ("i_" + "_".join(inter.split())) for inter in recommendations_list
    ]

    # Calculate mean success rate among people who took the recommended interventions
    mean_success_rate = []
    for rec in recommendations:
        took_rec = sub_group[sub_group[rec] == 1.0]
        mean_success_rate.append(took_rec["ttj_sub_12"].astype(int).mean())

    if not mean_success_rate:
        print("warning: no successful examples")
        average = 0.0
    else:
        average = sum(mean_success_rate) / len(mean_success_rate)

    error = abs(predicted_prob_success - average)

    return error


def get_aggregate_recommendation_error(
    training_set: pd.DataFrame,
    test_set: pd.DataFrame,
    model: BaseEstimator,
    set_size: int,
    num_recs: int,
    percent_sample: float,
):
    """
    Wrapper function which:
    - prepares the datasets
    - takes a random sample
    - applies the get_top_recommendations function to the sample
    - applies the eval_recommendations function to the sample
    - returns average error across sample

    :param training_set: Training set generated by pipeline
    :param test_set: Test set generated by pipeline
    :param model: Supervised model generated by pipeline
    :param set_size: Set size parameter for get_top_recommendations function
    :param num_recs: n parameter for get_top_recommendations function
    :param percent_sample: Percentage of test set to include in sample
    :return recommend-error: Aggregate average error
    """

    full_dataset = training_set.append(test_set)

    test_dataset = test_set.drop(columns=["ttj", "ttj_sub_12"])

    sample = test_dataset.sample(frac=percent_sample, random_state=1)

    sample["recommendations"] = sample.apply(
        lambda x: list(get_top_recommendations(model, x, set_size, num_recs).iloc[0]),
        axis=1,
    )

    sample["recommend_error"] = sample.apply(
        lambda x: eval_recommendations(x, full_dataset, x["recommendations"]), axis=1
    )

    return sample["recommend_error"].mean()
