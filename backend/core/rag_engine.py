import os
from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from .vector_store import build_vector_store, load_vector_store, get_retriever

SYSTEM_PROMPT = """You are an expert meeting assistant. Answer the user's question
based ONLY on the meeting transcript context provided below.

If the answer is not found in the context, say:
"I could not find this information in the meeting transcript."

Always be concise and precise. If quoting someone, mention it clearly.

Context from meeting transcript:
{context}"""


def get_llm():
    return ChatMistralAI(
        model="mistral-small-latest",
        mistral_api_key=os.getenv("MISTRAL_API_KEY"),
        temperature=0.3,
    )

def format_docs(docs):
    return "\n\n".join([doc.page_content for doc in docs])


def _chain_from_vector_store(vector_store):
    retriever = get_retriever(vector_store, k = 4)

    llm = get_llm()

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{question}"),
    ])

    #full LCEL Rag pipeline

    rag_chain = (

        {"context" : retriever | RunnableLambda(format_docs),
         "question": RunnablePassthrough()
         }
         |prompt|llm|StrOutputParser()
    )

    return rag_chain


def build_rag_chain(transcript:str, job_id:str):
    return _chain_from_vector_store(build_vector_store(transcript, job_id))


def load_rag_chain(job_id:str):
    """
    Rebuild a job's chain from Postgres on demand. Chat is served this way rather
    than by holding chains in process memory, so answers survive a Render restart.
    """
    return _chain_from_vector_store(load_vector_store(job_id))


def ask_question(rag_chain, question:str) -> str:
    print(f"Question : {question}")
    answer = rag_chain.invoke(question)
    print(f"answer :{answer}")
    return answer
