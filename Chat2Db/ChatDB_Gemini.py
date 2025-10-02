import streamlit as st
import pyodbc
import google.generativeai as genai
import pandas as pd

# ------------------------------
# 1. Configure Gemini
# ------------------------------
genai.configure(api_key="***")  # replace with your Gemini API key

# ------------------------------
# 2. Connect to AdventureWorksDW2019
# ------------------------------
@st.cache_resource
def init_connection():
    return pyodbc.connect(
        "DRIVER={SQL Server};"
        "SERVER=.;"     # change to your SQL Server
        "DATABASE=AdventureWorksDW2019;"
        "Trusted_Connection=yes;"
    )

conn = init_connection()
cursor = conn.cursor()

# ------------------------------
# 3. Extract schema from DB
# ------------------------------
@st.cache_data
def get_table_schema(table_name, schema="dbo"):
    query = f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table_name}'
    """
    cursor.execute(query)
    return [row[0] for row in cursor.fetchall()]

tables = ["DimEmployee", "DimCustomer", "DimProduct", "DimDate", "FactResellerSales", "FactInternetSales"]
schema_info = {t: get_table_schema(t) for t in tables}

schema_text = "\n".join(
    [f"{table}({', '.join(cols)})" for table, cols in schema_info.items()]
)

# ------------------------------
# 4. Ask Gemini to generate SQL
# ------------------------------
def get_sql_from_gemini(question, schema_text):
    prompt = f"""
You are an expert in Microsoft SQL Server.
Generate a safe SQL SELECT query for this schema:

Schema:
{schema_text}

Question:
{question}

Rules:
- Only return a SELECT statement.
- Use correct column names from schema.
- If aggregations are needed, use SUM or COUNT properly.
- Always include TOP N if the user asks for limited results.
- Always use ORDER BY if ranking is implied.

SQL:
"""
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)
    sql_query = response.text.strip()

    if "SELECT" in sql_query.upper():
        sql_query = sql_query[sql_query.upper().find("SELECT"):]
    return sql_query

# ------------------------------
# 5. Validate & clean SQL
# ------------------------------
def clean_sql_query(sql_query, schema_info):
    sql_query = sql_query.replace("```sql", "").replace("```", "")
    sql_query = sql_query.strip("` \n\r\t")
    sql_query = sql_query.replace("\\r", " ").replace("\\n", " ")
    sql_query = sql_query.replace("\r", " ").replace("\n", " ")
    sql_query = " ".join(sql_query.split())

    if not sql_query.lower().startswith("select"):
        raise ValueError("Only SELECT queries are allowed.")

    if sql_query.endswith(";"):
        sql_query = sql_query[:-1]

    all_columns = {col for cols in schema_info.values() for col in cols}
    for word in sql_query.replace(",", " ").replace("(", " ").replace(")", " ").split():
        if "." in word:
            col = word.split(".")[-1]
            if col not in all_columns:
                st.warning(f"Column not in schema: {col}")

    return sql_query

# ------------------------------
# 6. Execute SQL safely
# ------------------------------
def execute_sql(sql_query):
    cursor.execute(sql_query)
    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame.from_records(rows, columns=columns)

# ------------------------------
# 7. Streamlit App
# ------------------------------
st.title("💬 Natural Language to SQL with Gemini & AdventureWorksDW2019")

user_question = st.text_area("Enter your question:", placeholder="e.g. List products with sales greater than $1,000 in 2013")

if st.button("Generate & Run SQL"):
    if not user_question.strip():
        st.error("Please enter a question.")
    else:
        try:
            sql = get_sql_from_gemini(user_question, schema_text)
            st.subheader("Generated SQL from Gemini")
            st.code(sql, language="sql")

            sql = clean_sql_query(sql, schema_info)
            st.subheader("Cleaned SQL")
            st.code(sql, language="sql")

            result_df = execute_sql(sql)
            st.subheader("Query Result")
            st.dataframe(result_df, use_container_width=True)

        except Exception as e:
            st.error(f"Error: {e}")
