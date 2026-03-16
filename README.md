# 🧠 Yuan-Yuan's AI Knowledge Base Assistant

A Retrieval-Augmented Generation (RAG) system designed to transform curated Confluence documentation into a searchable, intelligent assistant.

## 🚀 Overview
This project was developed to centralize and democratize "tribal knowledge" within an enterprise environment. By indexing curated Confluence pages, the assistant provides accurate, cited answers to complex technical questions, such as SAS migration workflows.

## 🏛️ Architecture
The system is divided into a two-pillar architecture to separate data engineering from the user interface:

### 🔄 System Workflow
```mermaid
graph TD
    A[Confluence Favorites] -->|REST API| B(Pillar A: Ingestion)
    B --> C{Recursive Crawler}
    C -->|Discover Links| D[Linked Pages]
    D --> E[HTML Cleaning & Chunking]
    E -->|Sentence Transformer| F[(ChromaDB Vector Store)]
    
    G[User Query] -->| H(Pillar B: Retrieval)| H[Vector Similarity Search]
    F -->|Relevant Context| H
    H --> I[Azure OpenAI GPT-4o-mini]
    I --> J[Generated Answer]
    J --> K[BERT Semantic Evaluation]
    K --> L[Final Answer + Confidence Score]
```    
- **Pillar A (Ingestion):** A recursive crawler that discovers Confluence pages, cleans HTML content, and generates 384-dimensional vector embeddings using a local `all-MiniLM-L6-v2` transformer.
- **Pillar B (Interface):** A RAG-based chat interface utilizing **Azure OpenAI (GPT-4o-mini)**. It includes a local **BERT-based semantic evaluator** to score the quality of AI responses.

## 🛠️ Tech Stack
- **Language:** Python
- **Vector Database:** ChromaDB
- **LLM:** Azure OpenAI
- **Embeddings/Evaluation:** Sentence-Transformers (BERT)
- **Environment:** Hosted on internal Linux Server (Gershwin)

## 📁 Project Structure
```
Yuan_Yuan_RAG/
├── Data_Ingestion_Pipeline.ipynb   # Pillar A: Data factory & Vectorization
├── Yuan_Yuan_RAG_Interface.ipynb   # Pillar B: Chat UI & BERT Evaluation
├── rag_util.py                     # Shared utility functions (API, Cleaning, Logic)
├── .env.example                    # Template for required environment variables
└── requirements.txt                # List of Python dependencies
```