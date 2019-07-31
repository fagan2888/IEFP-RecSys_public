import luigi
import pandas as pd
import yaml

from luigi.contrib.s3 import S3Target
from sqlalchemy import create_engine


class ExtractPedidos(luigi.Task):
    def run(self):
        sigae_cols = yaml.load(
            open("./conf/base/sigae_columns.yml"), Loader=yaml.FullLoader
        )

        table = "pedidos"
        limit = 15000000

        query = """
        select {}
        from {}
        order by ano_mes desc
        limit {}
        """.format(
            ", ".join(sigae_cols[table]), table, limit
        )

        paths = query_to_parquet(query, self.output().path, chunksize=limit / 10)
        concat_parquet(paths, self.output().path)

    def output(self):
        buckets = yaml.load(open("./conf/base/buckets.yml"), Loader=yaml.FullLoader)
        target_path = buckets["intermediate"]["filter"]

        return S3Target(target_path + "pedidos.parquet")


class ExtractInterventions(luigi.Task):
    def run(self):
        sigae_cols = yaml.load(
            open("./conf/base/sigae_columns.yml"), Loader=yaml.FullLoader
        )

        table = "intervencoes"
        limit = 1500000

        query = """
        select {}
        from {}
        order by ano_mes desc
        limit {}
        """.format(
            ", ".join(sigae_cols[table]), table, limit
        )

        paths = query_to_parquet(query, self.output().path, chunksize=limit / 10)
        concat_parquet(paths, self.output().path)

    def output(self):
        buckets = yaml.load(open("./conf/base/buckets.yml"), Loader=yaml.FullLoader)
        target_path = buckets["intermediate"]["filter"]

        return S3Target(target_path + "interventions.parquet")


def concat_parquet(paths, s3path):
    dfs = []
    for path in paths:
        df = pd.read_parquet(path)
        df_dates = df.select_dtypes("datetime")
        df_dates = df_dates.astype("datetime64[s]")
        df[df_dates.columns] = df_dates
        dfs.append(df)

    df = pd.concat(dfs)
    df.to_parquet(s3path)


def query_to_parquet(query, s3path, chunksize):
    creds = yaml.load(open("./conf/local/credentials.yml"), Loader=yaml.FullLoader)
    pg_cred = creds["db"]

    url = "postgresql://{}:{}@{}:{}/{}"
    url = url.format(
        pg_cred["pg_user"], pg_cred["pg_pass"], pg_cred["pg_host"], 5432, "iefp"
    )
    con = create_engine(url, client_encoding="utf8")

    files = list()
    i = 0
    for chunk in pd.read_sql(query, con, chunksize=chunksize):
        temp_path = s3path + "_temp{}".format(i)
        chunk.to_parquet(temp_path)
        files.append(temp_path)
        i = i + 1

    return files
