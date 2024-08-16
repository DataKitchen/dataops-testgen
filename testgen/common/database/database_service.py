import concurrent.futures
import csv
import importlib
import logging
import queue as qu
import threading
from contextlib import suppress
from io import StringIO
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError

from testgen import settings
from testgen.common.credentials import (
    get_tg_db,
    get_tg_host,
    get_tg_password,
    get_tg_port,
    get_tg_schema,
    get_tg_username,
)
from testgen.common.encrypt import DecryptText
from testgen.common.read_file import get_template_files

LOG = logging.getLogger("testgen")


class CConnectParms:
    connectname = ""
    projectcode = ""
    connectid = ""
    hostname = ""
    port = ""
    dbname = ""
    schemaname = ""
    username = ""
    sql_flavor = ""
    url = ""
    connect_by_url = ""
    connect_by_key = ""
    private_key = ""
    private_key_passphrase = ""
    password = None

    def __init__(self, connectname):
        self.connectname = connectname


# Initialize variables global to this script
clsConnectParms = CConnectParms("NONE")
dctDBEngines = {}


def QuoteCSVItems(str_csv_row, char_quote='"'):
    if str_csv_row:
        lst_values = str_csv_row.split(",")
        # Process each value individually, quoting it if not already quoted
        str_quoted_values = ",".join(
            [
                (
                    f"{char_quote}{value}{char_quote}"
                    if not (value.startswith(char_quote) and value.endswith(char_quote))
                    else value
                )
                for value in lst_values
            ]
        )
        return str_quoted_values
    return str_csv_row


def empty_cache():
    global dctDBEngines
    dctDBEngines = {}


def AssignConnectParms(
    projectcode,
    connectid,
    host,
    port,
    dbname,
    schema,
    user,
    flavor,
    url,
    connect_by_url,
    connect_by_key,
    private_key,
    private_key_passphrase,
    connectname="PROJECT",
    password=None,
):
    global clsConnectParms

    clsConnectParms.connectname = connectname
    clsConnectParms.projectcode = projectcode
    clsConnectParms.connectid = connectid
    clsConnectParms.hostname = host
    clsConnectParms.port = port
    clsConnectParms.dbname = dbname
    clsConnectParms.schemaname = schema
    clsConnectParms.username = user
    clsConnectParms.sql_flavor = flavor
    clsConnectParms.password = password
    clsConnectParms.url = url
    clsConnectParms.connect_by_url = connect_by_url
    clsConnectParms.connect_by_key = connect_by_key
    clsConnectParms.private_key = private_key
    clsConnectParms.private_key_passphrase = private_key_passphrase


def _RetrieveProjectPW(strProjectCode, strConnID):
    strSQL = """ SELECT project_pw_encrypted
                   FROM connections cc
                  WHERE cc.project_code = '{PROJECT_CODE}' AND cc.connection_id = {CONNECTION_ID}; """

    # Replace Parameters
    strSQL = strSQL.replace("{PROJECT_CODE}", strProjectCode)
    strSQL = strSQL.replace("{CONNECTION_ID}", str(strConnID))
    # Execute Query
    strPW = RetrieveSingleResultValue("DKTG", strSQL)
    # Convert Postgres bytea to Python byte array
    strPW = bytes(strPW) if strPW else None

    # Perform Decryption
    strPW = DecryptText(strPW)
    return strPW


def _GetDBPassword(strCredentialSet):
    global clsConnectParms

    if strCredentialSet == "PROJECT":
        if not clsConnectParms.password:
            strPW = _RetrieveProjectPW(clsConnectParms.projectcode, clsConnectParms.connectid)
        else:
            strPW = clsConnectParms.password
    elif strCredentialSet == "DKTG":
        strPW = get_tg_password()
    else:
        raise ValueError('Credential Set "' + strCredentialSet + '" is unknown.')

    if strPW == "":
        raise ValueError('Password for Credential Set "' + strCredentialSet + '" is unknown.')
    else:
        return strPW


def get_db_type(sql_flavor):
    # This is for connection purposes. sqlalchemy 1.4.46 uses postgresql to connect to redshift database
    if sql_flavor == "redshift":
        return "postgresql"
    else:
        return sql_flavor


def _GetDBCredentials(strCredentialSet):
    global clsConnectParms

    if strCredentialSet == "PROJECT":
        # Check for unassigned parms
        if clsConnectParms.connectname == "NONE":
            raise ValueError("Project Connection Parameters were not set.")

        strConnectflavor = get_db_type(clsConnectParms.sql_flavor)

        # Get project credentials from clsConnectParms
        dctCredentials = {
            "name": strCredentialSet,
            "host": clsConnectParms.hostname,
            "port": clsConnectParms.port,
            "dbname": clsConnectParms.dbname,
            "dbschema": clsConnectParms.schemaname,
            "user": clsConnectParms.username,
            "flavor": strConnectflavor,
            "dbtype": clsConnectParms.sql_flavor,
            "url": clsConnectParms.url,
            "connect_by_url": clsConnectParms.connect_by_url,
            "connect_by_key": clsConnectParms.connect_by_key,
            "private_key": clsConnectParms.private_key,
            "private_key_passphrase": clsConnectParms.private_key_passphrase,
        }
    elif strCredentialSet == "DKTG":
        # Get credentials from functions in my_dk_credentials.py
        dctCredentials = {
            "name": strCredentialSet,
            "host": get_tg_host(),
            "port": get_tg_port(),
            "dbname": get_tg_db(),
            "dbschema": get_tg_schema(),
            "user": get_tg_username(),
            "flavor": "postgresql",
            "dbtype": "postgresql",
        }
    else:
        raise ValueError("Credentials for " + strCredentialSet + " are not defined.")

    return dctCredentials


def get_flavor_service(flavor):
    module_path = f"testgen.common.database.flavor.{flavor}_flavor_service"
    class_name = f"{flavor.capitalize()}FlavorService"
    module = importlib.import_module(module_path)
    flavor_class = getattr(module, class_name)
    return flavor_class()


def _InitDBConnection(strCredentialSet, strRaw="N", strAdmin="N", user_override=None, pwd_override=None):
    # Get DB Credentials
    dctCredentials = _GetDBCredentials(strCredentialSet)

    if strCredentialSet == "DKTG":
        con = _InitDBConnection_appdb(dctCredentials, strCredentialSet, strRaw, strAdmin, user_override, pwd_override)
    else:
        flavor_service = get_flavor_service(dctCredentials["dbtype"])
        flavor_service.init(dctCredentials)
        con = _InitDBConnection_target_db(flavor_service, strCredentialSet, strRaw, user_override, pwd_override)
    return con


def _InitDBConnection_appdb(
    dctCredentials, strCredentialSet, strRaw="N", strAdmin="N", user_override=None, pwd_override=None
):
    # Get DB Credentials
    dctCredentials = _GetDBCredentials(strCredentialSet)

    # Set DB Credential Overrides for Admin connections
    #    strAdmin = "N":  Log into DB/schema for normal stuff
    #    strAdmin = "D":  Log into postgres/public to create DB via override user/password
    #    strAdmin = "S":  Log into DB/public to create schema and run scripts via override user/password
    if strAdmin in {"D", "S"}:
        dctCredentials["user"] = user_override
        dctCredentials["dbschema"] = "public"
        if strAdmin == "D":
            dctCredentials["dbname"] = "postgres"

    # Get DBEngine using credentials
    if strCredentialSet in dctDBEngines and strAdmin == "N":
        # Retrieve existing engine from store
        dbEngine = dctDBEngines[strCredentialSet]
    else:
        # Handle Admin overrides or circumstantial password override
        if strAdmin in {"D", "S"} or pwd_override is not None:
            strPW = pwd_override
        else:
            strPW = _GetDBPassword(strCredentialSet)

        # Open a new engine with appropriate connection parms
        # STANDARD FORMAT:  strConnect = 'flavor://username:password@host:port/database'
        strConnect = "{}://{}:{}@{}:{}/{}".format(
            dctCredentials["flavor"],
            dctCredentials["user"],
            quote_plus(strPW),
            dctCredentials["host"],
            dctCredentials["port"],
            dctCredentials["dbname"],
        )
        try:
            # Timeout in seconds:  1 hour = 60 * 60 second = 3600
            dbEngine = create_engine(strConnect, connect_args={"connect_timeout": 3600})
            dctDBEngines[strCredentialSet] = dbEngine

        except SQLAlchemyError as e:
            raise ValueError(
                f"Failed to create engine (Admin={strAdmin}) \
                              for database {dctCredentials['dbname']}"
            ) from e

    # Second, create a connection from our engine
    try:
        if strRaw == "N":
            con = dbEngine.connect()
            if strAdmin == "N":
                strSchemaSQL = f"SET SEARCH_PATH = {dctCredentials['dbschema']};"
                con.execute(text(strSchemaSQL))
        else:
            con = dbEngine.raw_connection()
            strSchemaSQL = "SET SEARCH_PATH = " + dctCredentials["dbschema"]
            with con.cursor() as cur:
                cur.execute(strSchemaSQL)
            con.commit()
    except SQLAlchemyError as e:
        raise ValueError("Failed to connect to database " + dctCredentials["dbname"]) from e

    return con


def _InitDBConnection_target_db(flavor_service, strCredentialSet, strRaw="N", user_override=None, pwd_override=None):
    # Get DBEngine using credentials
    if strCredentialSet in dctDBEngines:
        # Retrieve existing engine from store
        dbEngine = dctDBEngines[strCredentialSet]
    else:
        # Handle user override
        if user_override is not None:
            flavor_service.override_user(user_override)
        # Handle password override
        if pwd_override is not None:
            strPW = pwd_override
        elif not flavor_service.is_connect_by_key():
            strPW = _GetDBPassword(strCredentialSet)
        else:
            strPW = None

        # Open a new engine with appropriate connection parms
        is_password_overwritten = pwd_override is not None
        strConnect = flavor_service.get_connection_string(strPW, is_password_overwritten)

        connect_args = {"connect_timeout": 3600}
        connect_args.update(flavor_service.get_connect_args(is_password_overwritten))

        try:
            # Timeout in seconds:  1 hour = 60 * 60 second = 3600
            dbEngine = create_engine(strConnect, connect_args=connect_args)
            dctDBEngines[strCredentialSet] = dbEngine

        except SQLAlchemyError as e:
            raise ValueError(f"Failed to create engine for database {flavor_service.get_db_name}") from e

    # Second, create a connection from our engine
    queries = flavor_service.get_pre_connection_queries()
    if strRaw == "N":
        connection = dbEngine.connect()
        for query in queries:
            try:
                connection.execute(text(query))
            except Exception:
                LOG.warning(
                    f"failed executing pre connection query: `{query}`",
                    exc_info=settings.IS_DEBUG,
                    stack_info=settings.IS_DEBUG,
                )
    else:
        connection = dbEngine.raw_connection()
        with connection.cursor() as cur:
            for query in queries:
                try:
                    cur.execute(query)
                except Exception:
                    LOG.warning(
                        f"failed executing pre connection query: `{query}`",
                        exc_info=settings.IS_DEBUG,
                        stack_info=settings.IS_DEBUG,
                    )
        connection.commit()

    return connection


def CreateDatabaseIfNotExists(strDBName: str, params_mapping: dict, delete_db: bool, drop_users_and_roles: bool = True):
    LOG.info("CurrentDB Operation: CreateDatabase. Creds: DKTG Admin")

    con = _InitDBConnection(
        "DKTG",
        strAdmin="D",
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        pwd_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
    )
    con.execute("commit")

    # Catch and ignore error if database already exists
    with con:
        if delete_db:
            con.execute(
                f"SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = '{strDBName}'"
            )
            con.execute("commit")
            con.execute(f"DROP DATABASE IF EXISTS {strDBName}")
            con.execute("commit")
            if drop_users_and_roles:
                con.execute(replace_params("DROP USER IF EXISTS {TESTGEN_USER}", params_mapping))
                con.execute(replace_params("DROP USER IF EXISTS {TESTGEN_REPORT_USER}", params_mapping))
                con.execute("DROP ROLE IF EXISTS testgen_execute_role")
                con.execute("DROP ROLE IF EXISTS testgen_report_role")
                con.execute("commit")
        with suppress(ProgrammingError):
            con.execute("create database " + strDBName)
            con.close()


def RunActionQueryList(strCredentialSet, lstQueries, strAdminNDS="N", user_override=None, pwd_override=None):
    LOG.info("CurrentDB Operation: RunActionQueryList. Creds: %s", strCredentialSet)

    with _InitDBConnection(
        strCredentialSet, strAdmin=strAdminNDS, user_override=user_override, pwd_override=pwd_override
    ) as con:
        i = 0
        n = len(lstQueries)
        lstInsertedIds = []
        if n == 0:
            LOG.info("No queries to process")
        for q in lstQueries:
            i += 1
            LOG.debug(f"LastQuery = {q}")
            LOG.info(f"(Processing {i} of {n})")
            tx = con.begin()
            exQ = con.execute(text(q))
            if exQ.rowcount == -1:
                strMsg = "Action query processed no records."
            else:
                strMsg = str(exQ.rowcount) + " records processed."

                try:
                    lstInsertedIds.append(exQ.fetchone()[0])
                except Exception:
                    lstInsertedIds.append(None)

            tx.commit()
            LOG.info(strMsg)

    return lstInsertedIds



def RunRetrievalQueryList(strCredentialSet, lstQueries):
    LOG.info("CurrentDB Operation: RunRetrievalQueryList. Creds: %s", strCredentialSet)

    with _InitDBConnection(strCredentialSet) as con:
        colNames = None
        lstResults = []
        i = 0
        n = len(lstQueries)
        if n == 0:
            LOG.info("No queries to process")
        for q in lstQueries:
            i += 1
            LOG.debug("LastQuery = %s", q)
            LOG.info("(Processing %s of %s)", i, n)

            exQ = con.execute(text(q))
            lstOneResult = exQ.fetchall()
            if not colNames:
                colNames = exQ.keys()
            strRows = str(exQ.rowcount)
            lstResults.extend(lstOneResult)

            LOG.info("%s records retrieved.", strRows)

        return lstResults, colNames


class _CThreadedFetch:
    def __init__(self, strCredentialSet, count_lock):
        self.strCredentialSet = strCredentialSet
        self.count_lock = count_lock
        self.count = 0

    def __call__(self, strQuery):
        colNames = None
        lstResult = None
        booError = False

        with self.count_lock:
            self.count += 1
            i = self.count

        try:
            with _InitDBConnection(self.strCredentialSet) as con:
                try:
                    exQ = con.execute(text(strQuery))
                    lstResult = exQ.fetchall()
                    if not colNames:
                        colNames = exQ.keys()
                    LOG.info("(Processed Threaded Query %s on thread %s)", i, threading.current_thread().name)
                except Exception:
                    LOG.exception(f"Failed Query. LastQuery: {strQuery}")
                    booError = True
        except Exception as e:
            LOG.info("LastQuery: %s", strQuery)
            raise ValueError(f"Failed to execute threaded query: {e}") from e
        else:
            return lstResult, colNames, booError


def RunThreadedRetrievalQueryList(strCredentialSet, lstQueries, intMaxThreads, spinner):
    LOG.info("CurrentDB Operation: RunThreadedRetrievalQueryList. Creds: %s", strCredentialSet)

    lstResults = []
    colNames = []
    intErrors = 0

    if intMaxThreads is None:
        intMaxThreads = 4
    elif intMaxThreads < 1 or intMaxThreads > 10:
        intMaxThreads = 4

    qq = qu.Queue()

    for query in lstQueries:
        qq.put(query)

    # Initialize count and lock
    count_lock = threading.Lock()

    clsThreadedFetch = _CThreadedFetch(strCredentialSet, count_lock)

    with concurrent.futures.ThreadPoolExecutor(max_workers=intMaxThreads) as executor:
        try:
            futures = []
            while not qq.empty():
                query = qq.get()
                futures.append(executor.submit(clsThreadedFetch, query))

            for future in futures:
                lstOneResult, colName, booError = future.result()
                if spinner:
                    spinner.next()
                intErrors += 1 if booError else 0
                if lstOneResult:
                    lstResults.append(lstOneResult)
                    colNames = colName

        except Exception:
            LOG.exception("Failed to execute threaded queries")

    lstResults = [element for sublist in lstResults for element in sublist]

    return lstResults, colNames, intErrors


def RetrieveDBResultsToList(strCredentialSet, strRunSQL):
    LOG.info("CurrentDB Operation: RetrieveDBResultsToList. Creds: %s", strCredentialSet)

    with _InitDBConnection(strCredentialSet) as con:
        exQ = con.execute(text(strRunSQL))
        lstResults = exQ.fetchall()
        colNames = exQ.keys()

        LOG.debug("Last Query='%s'", strRunSQL)
        LOG.debug("%s records retrieved.", exQ.rowcount)

        return lstResults, colNames


def RetrieveDBResultsToDictList(strCredentialSet, strRunSQL):
    LOG.info("CurrentDB Operation: RetrieveDBResultsToDictList. Creds: %s", strCredentialSet)
    LOG.info("(Processing Query)")

    with _InitDBConnection(strCredentialSet) as con:
        LOG.debug("Last Query='%s'", strRunSQL)
        exQ = con.execute(text(strRunSQL))

        # Creates list of dictionaries so records are addressible by column name
        lstResults = [row._mapping for row in exQ]
        LOG.debug("%s records retrieved.", exQ.rowcount)

        return lstResults


def ExecuteDBQuery(strCredentialSet, strRunSQL):
    LOG.info("CurrentDB Operation: ExecuteDBQuery. Creds: %s", strCredentialSet)
    LOG.info("(Processing Query)")

    with _InitDBConnection(strCredentialSet) as con:
        LOG.debug("Last Query='%s'", strRunSQL)
        con.execute(text(strRunSQL))
        con.execute("commit")
        LOG.debug("Query ran.")


def RetrieveSingleResultValue(strCredentialSet, strRunSQL):
    LOG.info("CurrentDB Operation: RetrieveSingleResultValue. Creds: %s", strCredentialSet)

    with _InitDBConnection(strCredentialSet) as con:
        LOG.debug("Last Query='%s'", strRunSQL)
        lstResult = con.execute(text(strRunSQL)).fetchone()
        if lstResult:
            LOG.debug("Single result retrieved.")
            valReturn = lstResult[0]
            return valReturn
        else:
            LOG.debug("Single result NOT retrieved.")


def WriteListToDB(strCredentialSet, lstData, lstColumns, strDBTable):
    LOG.info("CurrentDB Operation: WriteListToDB. Creds: %s", strCredentialSet)
    LOG.debug("(Processing ingestion query: %s records)", lstData)
    # List should have same column names as destination table, though not all columns in table are required

    # Use COPY for DKTG database, otherwise executemany()

    con = _InitDBConnection(strCredentialSet, "Y")
    cur = con.cursor()
    if strCredentialSet == "DKTG":
        # Write List to CSV in memory
        sio = StringIO()
        writer = csv.writer(sio, quoting=csv.QUOTE_MINIMAL)
        writer.writerows(lstData)
        sio.seek(0)

        # Get list of column names for COPY statement
        strColumnNames = ", ".join(lstColumns)
        strCopySQL = f"COPY {strDBTable} ({strColumnNames}) FROM STDIN WITH (FORMAT CSV)"
        LOG.debug("Last Query='%s'", strCopySQL)

        cur.copy_expert(strCopySQL, sio)
        con.commit()

    else:
        # Get list of column names and column names formatted as parms
        strColumnNames = ", ".join(lstColumns)
        lstColumnParms = [":" + column_name for column_name in lstColumns]
        strColumnParms = ", ".join(lstColumnParms)

        # Prep data as list of dictionaries
        lstRowDicts = [dict(row) for row in lstData]

        strInsertSQL = "INSERT INTO " + strDBTable + "(" + strColumnNames + ")" + " VALUES (" + strColumnParms + ")"
        LOG.debug("Last Query='%s'", strInsertSQL)

        exQ = con.execute(text(strInsertSQL), lstRowDicts)
        con.commit()
        LOG.debug("%s records saved", exQ.rowcount)
    con.close()


def replace_params(query: str, params_mapping: dict) -> str:
    for key, value in params_mapping.items():
        query = query.replace(f"{{{key}}}", str(value))
    return query


def get_queries_for_command(sub_directory: str, params_mapping: dict, mask: str = r"^.*sql$", path: str | None = None) -> list[str]:
    files = sorted(get_template_files(mask=mask, sub_directory=sub_directory, path=path), key=lambda key: str(key))

    queries = []
    for file in files:
        query = file.read_text("utf-8")
        template = replace_params(query, params_mapping)

        queries.append(template)

    if len(queries) == 0:
        LOG.warning(f"No sql files were found for the mask {mask} in subdirectory {sub_directory}")

    return queries
