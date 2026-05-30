"""
Example demonstrating the Research RAG Pipeline for financial document analysis
"""
import asyncio
from typing import List, Dict, Any
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass


@dataclass
class FinancialDocument:
    """Represents a financial document"""
    doc_id: str
    title: str
    content: str
    issuer: str
    doc_type: str  # 10-K, 10-Q, earnings_call_transcript, research_note
    date: datetime
    metadata: Dict[str, Any]


class MockOpenSearch:
    """Mock implementation of OpenSearch for document indexing and retrieval"""
    
    def __init__(self):
        self.documents = []
        self.indexed_docs = {}
    
    def index_document(self, doc: FinancialDocument):
        """Index a document"""
        self.documents.append(doc)
        self.indexed_docs[doc.doc_id] = doc
        print(f"Indexed document in OpenSearch: {doc.doc_id} - {doc.title}")
    
    def search_bm25(self, query: str, issuer_filter: str = None) -> List[FinancialDocument]:
        """Perform BM25 search"""
        # Simple keyword matching for demonstration
        results = []
        query_lower = query.lower()
        
        for doc in self.documents:
            # Filter by issuer if provided
            if issuer_filter and doc.issuer.lower() != issuer_filter.lower():
                continue
                
            # Check if query terms appear in title or content
            if (query_lower in doc.title.lower() or 
                query_lower in doc.content.lower()):
                results.append(doc)
        
        # Sort by relevance (simple implementation)
        results.sort(key=lambda x: len([word for word in query_lower.split() 
                                      if word in x.title.lower() or word in x.content.lower()]), 
                    reverse=True)
        
        return results[:5]  # Return top 5 results


class MockQdrant:
    """Mock implementation of Qdrant for vector similarity search"""
    
    def __init__(self):
        self.vectors = {}
        self.documents = {}
    
    def add_document(self, doc_id: str, content: str, issuer: str):
        """Add document with vector representation"""
        # Create a simple embedding by taking hash of content
        embedding = self._simple_embed(content)
        self.vectors[doc_id] = embedding
        self.documents[doc_id] = content
        print(f"Added document to Qdrant: {doc_id}")
    
    def _simple_embed(self, text: str) -> np.ndarray:
        """Create a simple embedding using hash of text"""
        # This is a very simplified embedding for demo purposes
        text_hash = hash(text) % 1000000
        embedding = np.random.rand(32)  # 32-dimensional vector
        # Make embedding deterministic based on text hash
        np.random.seed(text_hash)
        embedding = np.random.rand(32)
        return embedding
    
    def search_vectors(self, query: str, issuer_filter: str = None, limit: int = 5, opensearch_docs: List = None) -> List[tuple]:
        """Search for similar documents using vector similarity"""
        query_embedding = self._simple_embed(query)
        
        similarities = []
        for doc_id, doc_embedding in self.vectors.items():
            # Calculate cosine similarity
            similarity = np.dot(query_embedding, doc_embedding) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(doc_embedding)
            )
            
            # Get corresponding document to check issuer filter
            doc_title = next((d.title for d in opensearch_docs if d.doc_id == doc_id), "")
            
            if issuer_filter:
                doc_issuer = next((d.issuer for d in opensearch_docs if d.doc_id == doc_id), "")
                if doc_issuer and doc_issuer.lower() != issuer_filter.lower():
                    continue
            
            similarities.append((doc_id, similarity))
        
        # Sort by similarity (highest first)
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:limit]


class MockNeo4j:
    """Mock implementation of Neo4j for graph-based retrieval"""
    
    def __init__(self):
        self.relationships = {}  # issuer -> related_issuers
        self.issuer_info = {}
    
    def add_relationship(self, issuer: str, related_issuer: str, relationship_type: str):
        """Add a relationship between issuers"""
        if issuer not in self.relationships:
            self.relationships[issuer] = []
        self.relationships[issuer].append((related_issuer, relationship_type))
        print(f"Added relationship in Neo4j: {issuer} -> {relationship_type} -> {related_issuer}")
    
    def add_issuer_info(self, issuer: str, sector: str, industry: str):
        """Add issuer information"""
        self.issuer_info[issuer] = {"sector": sector, "industry": industry}
    
    def get_related_entities(self, issuer: str) -> List[Dict[str, Any]]:
        """Get related entities for an issuer"""
        if issuer in self.relationships:
            return [{"issuer": rel[0], "relationship_type": rel[1]} 
                   for rel in self.relationships[issuer]]
        return []
    
    def get_sector_industry(self, issuer: str) -> Dict[str, str]:
        """Get sector and industry for an issuer"""
        return self.issuer_info.get(issuer, {"sector": "Unknown", "industry": "Unknown"})


class ResearchRAGPipeline:
    """Research RAG Pipeline Service with mock implementations"""
    
    def __init__(self):
        """Initialize the research RAG pipeline service"""
        self.opensearch = MockOpenSearch()
        self.qdrant = MockQdrant()
        self.neo4j = MockNeo4j()
        self.documents = []
    
    def index_documents(self, documents: List[FinancialDocument]):
        """Index filings, transcripts, and research documents"""
        print(f"Indexing {len(documents)} documents into RAG system...")
        
        for doc in documents:
            # Index in OpenSearch for BM25 search
            self.opensearch.index_document(doc)
            
            # Add to Qdrant for vector search
            self.qdrant.add_document(doc.doc_id, doc.content, doc.issuer)
        
        self.documents.extend(documents)
    
    def hybrid_retrieval(self, query: str, issuer_filter: str = None) -> List[Dict[str, Any]]:
        """Perform hybrid retrieval using BM25 + vector + graph"""
        print(f"Performing hybrid retrieval for query: '{query}' with issuer filter: {issuer_filter}")
        
        # BM25 search
        bm25_results = self.opensearch.search_bm25(query, issuer_filter)
        print(f"BM25 results: {len(bm25_results)} documents")
        
        # Vector search
        vector_results = self.qdrant.search_vectors(query, issuer_filter, opensearch_docs=self.opensearch.documents)
        print(f"Vector results: {len(vector_results)} documents")
        
        # Graph search (get related entities)
        graph_results = []
        if issuer_filter:
            related_entities = self.neo4j.get_related_entities(issuer_filter)
            graph_results.extend(related_entities)
            print(f"Graph results for {issuer_filter}: {len(related_entities)} related entities")
        
        # Combine and rank results (simplified approach)
        combined_results = []
        
        # Add BM25 results
        for doc in bm25_results:
            combined_results.append({
                "id": doc.doc_id,
                "title": doc.title,
                "content": doc.content[:200] + "...",  # Truncate for display
                "issuer": doc.issuer,
                "doc_type": doc.doc_type,
                "date": doc.date,
                "source": "BM25",
                "score": 1.0  # Placeholder
            })
        
        # Add vector results
        for doc_id, similarity in vector_results:
            doc = next((d for d in self.documents if d.doc_id == doc_id), None)
            if doc:
                combined_results.append({
                    "id": doc.doc_id,
                    "title": doc.title,
                    "content": doc.content[:200] + "...",  # Truncate for display
                    "issuer": doc.issuer,
                    "doc_type": doc.doc_type,
                    "date": doc.date,
                    "source": "Vector",
                    "score": similarity
                })
        
        return combined_results
    
    def process_natural_language_query(self, query: str, issuer: str = None) -> Dict[str, Any]:
        """Process natural language queries for explanations and context"""
        print(f"\nProcessing natural language query: '{query}' for issuer: {issuer}")
        
        # Perform hybrid retrieval
        results = self.hybrid_retrieval(query, issuer)
        
        # Get related entities from graph if issuer is specified
        related_entities = []
        if issuer:
            related_entities = self.neo4j.get_related_entities(issuer)
        
        # Format response
        response = {
            "query": query,
                       "issuer": issuer,
            "results": results,
            "related_entities": related_entities,
            "response_summary": self._generate_response_summary(query, results)
        }
        
        return response
    
    def _generate_response_summary(self, query: str, results: List[Dict[str, Any]]) -> str:
        """Generate a summary response based on query and results"""
        if not results:
            return "No relevant documents found for the query."
        
        # Simple summary generation
        summary_parts = []
        
        # Group by source
        sources = {"BM25": [], "Vector": []}
        for result in results:
            sources[result["source"]].append(result)
        
        if sources["BM25"]:
            summary_parts.append(f"Found {len(sources['BM25'])} documents using keyword search (BM25).")
        
        if sources["Vector"]:
            summary_parts.append(f"Found {len(sources['Vector'])} documents using semantic similarity (vector search).")
        
        return " ".join(summary_parts)


def create_sample_documents():
    """Create sample financial documents for testing"""
    documents = [
        FinancialDocument(
            doc_id="doc_1",
            title="Apple Inc. Q4 2023 Earnings Call Transcript",
            content="Apple reported strong performance in Q4 2023 with revenue of $89.5B. iPhone sales were particularly strong, up 12% year-over-year. Management expressed optimism about new product launches and services growth. The company announced a new AI initiative called 'Apple Intelligence' that will integrate ChatGPT-like functionality across its ecosystem.",
            issuer="Apple",
            doc_type="earnings_call_transcript",
            date=datetime(2023, 11, 2),
            metadata={"quarter": "Q4 2023", "revenue": 89.5, "eps": 2.12}
        ),
        FinancialDocument(
            doc_id="doc_2",
            title="Microsoft Corp. Q4 2023 Earnings Call Transcript",
            content="Microsoft's Azure cloud business grew 31% year-over-year, continuing to drive strong growth. Office 365 subscription revenue was up 15%. The company announced integration of OpenAI's technology across more of its products. CFO Amy Hood discussed capital allocation priorities and the company's approach to the competitive landscape.",
            issuer="Microsoft",
            doc_type="earnings_call_transcript",
            date=datetime(2023, 10, 24),
            metadata={"quarter": "Q4 2023", "revenue": 56.8, "eps": 2.99}
        ),
        FinancialDocument(
            doc_id="doc_3",
            title="Google LLC Q4 2023 Earnings Call Transcript",
            content="Google Cloud revenue grew 28% year-over-year, with strong performance in infrastructure and AI-related services. CEO Sundar Pichai emphasized investments in artificial intelligence and machine learning. The company reported challenges in traditional advertising business but showed improvement in YouTube ad revenue.",
            issuer="Google",
            doc_type="earnings_call_transcript",
            date=datetime(2023, 10, 25),
            metadata={"quarter": "Q4 2023", "revenue": 86.8, "eps": 1.55}
        ),
        FinancialDocument(
            doc_id="doc_4",
            title="Tesla Inc. Q4 2023 Earnings Call Transcript",
            content="Tesla delivered 484,500 vehicles in Q4 2023, a record for the company. Energy storage deployments increased 40% quarter-over-quarter. CEO Elon Musk discussed plans for a new AI training supercomputer and autonomous driving progress. The company also announced expansion of its Supercharger network with new pricing for non-Tesla vehicles.",
            issuer="Tesla",
            doc_type="earnings_call_transcript",
            date=datetime(2023, 1, 25),
            metadata={"quarter": "Q4 2023", "revenue": 24.3, "eps": 0.52}
        )
    ]
    
    return documents


async def research_rag_example():
    """
    Example demonstrating the Research RAG Pipeline
    """
    print("="*100)
    print("FINANCIAL ALPHA & RISK RESEARCH LAB - RESEARCH RAG PIPELINE EXAMPLE")
    print("Demonstrating AI-powered financial document analysis and retrieval")
    print("="*100)
    
    # Initialize the RAG pipeline
    rag_pipeline = ResearchRAGPipeline()
    
    # Add some relationships to the graph database
    rag_pipeline.neo4j.add_relationship("Apple", "Microsoft", "competitor")
    rag_pipeline.neo4j.add_relationship("Apple", "Google", "competitor")
    rag_pipeline.neo4j.add_relationship("Microsoft", "Google", "competitor")
    rag_pipeline.neo4j.add_relationship("Microsoft", "NVIDIA", "partner")
    rag_pipeline.neo4j.add_relationship("Google", "NVIDIA", "partner")
    
    rag_pipeline.neo4j.add_issuer_info("Apple", "Technology", "Consumer Electronics")
    rag_pipeline.neo4j.add_issuer_info("Microsoft", "Technology", "Software & Services")
    rag_pipeline.neo4j.add_issuer_info("Google", "Technology", "Internet & Services")
    rag_pipeline.neo4j.add_issuer_info("Tesla", "Automotive", "Electric Vehicles")
    
    # Create and index sample documents
    print("\n[INDEXING PHASE]")
    documents = create_sample_documents()
    rag_pipeline.index_documents(documents)
    
    # Example queries
    queries = [
        ("What did Apple say about AI?", "Apple"),
        ("How is cloud computing performing for tech companies?", None),
        ("What did Tesla report about vehicle deliveries?", "Tesla")
    ]
    
    print("\n[RETRIEVAL PHASE]")
    for i, (query, issuer) in enumerate(queries, 1):
        print(f"\n--- Query {i}: {query} ---")
        
        # Process the natural language query
        response = rag_pipeline.process_natural_language_query(query, issuer)
        
        print(f"Query: {response['query']}")
        print(f"Issuer: {response['issuer']}")
        print(f"Number of results: {len(response['results'])}")
        print(f"Response Summary: {response['response_summary']}")
        
        if response['related_entities']:
            print(f"Related entities: {[e['issuer'] for e in response['related_entities']]}")
        
        # Display top results
        for j, result in enumerate(response['results'][:2], 1):  # Show top 2 results
            print(f"  Result {j}: {result['title']} ({result['source']})")
            print(f"    Content preview: {result['content']}")
            print()
    
    print("="*100)
    print("RESEARCH RAG PIPELINE EXAMPLE COMPLETED")
    print("="*100)
    
    return rag_pipeline


def main():
    """
    Main function to run the research RAG pipeline example
    """
    # Run the async RAG example
    result = asyncio.run(research_rag_example())
    return result


if __name__ == "__main__":
    main()