import os
import tempfile
import streamlit as st
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEndpoint
from huggingface_hub import InferenceClient

try:
    from langchain.text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

# Sayfa ayarları
st.set_page_config(page_title="RAG Chatbot", page_icon="🤖", layout="wide")
st.title("🤖 RAG Tabanlı Akıllı Chatbot")
st.caption("Retrieval Augmented Generation ile Döküman Bazlı Soru-Cevap Sistemi")

# Sidebar
with st.sidebar:
    st.header("⚙️ Ayarlar")
    hf_token = st.text_input("Hugging Face Token", type="password")

    model_name = st.selectbox(
        "LLM Modeli",
        [
            "google/flan-t5-large",  # En stabil
            "google/flan-t5-xl",
            "meta-llama/Llama-2-7b-chat-hf",
            "mistralai/Mistral-7B-Instruct-v0.1",
        ]
    )

    st.subheader("RAG Parametreleri")
    chunk_size = st.slider("Chunk Size", 200, 2000, 500, 100)
    chunk_overlap = st.slider("Chunk Overlap", 0, 200, 50, 25)
    k_documents = st.slider("K Documents", 1, 5, 3)

    st.subheader("Model Parametreleri")
    temperature = st.slider("Temperature", 0.0, 1.0, 0.3, 0.1)
    max_tokens = st.slider("Max Tokens", 128, 1024, 512, 64)

# Session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "vectorstore" not in st.session_state:
    st.session_state.vectorstore = None
if "retriever" not in st.session_state:
    st.session_state.retriever = None

col1, col2 = st.columns([2, 1])

# Döküman yükleme
with col1:
    st.header("📚 Döküman Yükleme")
    uploaded_files = st.file_uploader(
        "PDF veya TXT dosyalarınızı yükleyin",
        type=["pdf", "txt", "md"],
        accept_multiple_files=True
    )

    if st.button("🔄 RAG Sistemi Oluştur", type="primary", use_container_width=True):
        if not hf_token:
            st.error("❌ Token girin!")
        elif not uploaded_files:
            st.error("❌ Dosya yükleyin!")
        else:
            with st.spinner("İşleniyor..."):
                try:
                    # Dosyaları yükle
                    temp_dir = tempfile.mkdtemp()
                    documents = []

                    for file in uploaded_files:
                        path = os.path.join(temp_dir, file.name)
                        with open(path, "wb") as f:
                            f.write(file.getbuffer())

                        if file.name.endswith('.pdf'):
                            loader = PyPDFLoader(path)
                        else:
                            loader = TextLoader(path, encoding='utf-8')

                        documents.extend(loader.load())

                    st.success(f"✅ {len(documents)} sayfa yüklendi")

                    # Parçala
                    splitter = RecursiveCharacterTextSplitter(
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap
                    )
                    chunks = splitter.split_documents(documents)
                    st.success(f"✅ {len(chunks)} chunk oluşturuldu")

                    # Embeddings & FAISS
                    embeddings = HuggingFaceEmbeddings(
                        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
                    )
                    vectorstore = FAISS.from_documents(chunks, embeddings)
                    st.session_state.vectorstore = vectorstore
                    st.session_state.retriever = vectorstore.as_retriever(
                        search_kwargs={"k": k_documents}
                    )

                    st.success("✅ RAG sistemi hazır!")
                    st.balloons()

                except Exception as e:
                    st.error(f"❌ Hata: {e}")

# Durum paneli
with col2:
    st.header("ℹ️ Durum")
    if st.session_state.vectorstore:
        st.success("✅ Vektör DB: Aktif")
    else:
        st.warning("⚠️ Vektör DB: Yok")

# Chat
st.header("💬 Sohbet")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sources" in msg:
            with st.expander("📚 Kaynaklar"):
                for i, src in enumerate(msg["sources"], 1):
                    st.text(f"Kaynak {i}: {src[:300]}...")

if prompt := st.chat_input("Sorunuz..."):
    if not st.session_state.retriever:
        st.error("❌ Önce döküman yükleyin!")
    elif not hf_token:
        st.error("❌ Token girin!")
    else:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Düşünüyorum..."):
                try:
                    # Retrieval
                    docs = st.session_state.retriever.get_relevant_documents(prompt)
                    context = "\n\n".join([doc.page_content for doc in docs])

                    # LLM ile yanıt
                    client = InferenceClient(token=hf_token)

                    # Model için doğru parametreler
                    model_params = {
                        "max_new_tokens": max_tokens,
                        "temperature": temperature,
                        "return_full_text": False,
                    }

                    # Bazı modeller için özel ayarlar
                    if "flan-t5" in model_name.lower():
                        model_params["do_sample"] = False

                    full_prompt = f"""Soruyu bağlama göre yanıtla. Bilmiyorsan 'bilmiyorum' de.

Bağlam: {context[:2000]}

Soru: {prompt}

Yanıt:"""

                    response = client.text_generation(
                        full_prompt,
                        model=model_name,
                        **model_params
                    )

                    st.markdown(response)

                    with st.expander(f"📚 Kaynaklar ({len(docs)} adet)"):
                        for i, doc in enumerate(docs, 1):
                            st.text(f"Kaynak {i}: {doc.page_content[:300]}...")

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response,
                        "sources": [d.page_content[:300] for d in docs]
                    })

                except Exception as e:
                    st.error(f"❌ Hata: {e}")

if st.button("🗑️ Temizle"):
    st.session_state.messages = []
    st.rerun()