Basic RAG

Retrieval-augmented generation (RAG) is an AI framework that synergizes the capabilities of LLMs and information retrieval systems. It's useful to answer questions or generate content leveraging external knowledge. There are two main steps in RAG:

    retrieval: retrieve relevant information from a knowledge base or an external source, for example, using text embeddings stored in a vector store.
    generation: insert the relevant information to the prompt for the LLM to generate information.

In this guide, we will walk through a very basic example of RAG, you can find more in depth guides in our cookbooks.
Open In Colab
RAG from scratch

This section aims to guide you through the process of building a basic RAG from scratch. We have two goals: firstly, to offer users a comprehensive understanding of the internal workings of RAG and demystify the underlying mechanisms; secondly, to empower you with the essential foundations needed to build an RAG using the minimum required dependencies.
Import needed packages

The first step is to install the packages mistralai and faiss-cpu and import the needed packages:

from mistralai import Mistral
import requests
import numpy as np
import faiss
import os
from getpass import getpass

api_key= getpass("Type your API Key")
client = Mistral(api_key=api_key)

Get data

In this very simple example, we are getting data from an essay written by Paul Graham:

response = requests.get('https://raw.githubusercontent.com/run-llama/llama_index/main/docs/docs/examples/data/paul_graham/paul_graham_essay.txt')
text = response.text

We can also save the essay in a local file:

f = open('essay.txt', 'w')
f.write(text)
f.close()

Split document into chunks

In a RAG system, it is crucial to split the document into smaller chunks so that it's more effective to identify and retrieve the most relevant information in the retrieval process later. In this example, we simply split our text by character, combine 2048 characters into each chunk, and we get 37 chunks.

chunk_size = 2048
chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
len(chunks)

Output

37

Considerations:

    Chunk size: Depending on your specific use case, it may be necessary to customize or experiment with different chunk sizes and chunk overlap to achieve optimal performance in RAG. For example, smaller chunks can be more beneficial in retrieval processes, as larger text chunks often contain filler text that can obscure the semantic representation. As such, using smaller text chunks in the retrieval process can enable the RAG system to identify and extract relevant information more effectively and accurately. However, it's worth considering the trade-offs that come with using smaller chunks, such as increasing processing time and computational resources.
    How to split: While the simplest method is to split the text by character, there are other options depending on the use case and document structure. For example, to avoid exceeding token limits in API calls, it may be necessary to split the text by tokens. To maintain the cohesiveness of the chunks, it can be useful to split the text by sentences, paragraphs, or HTML headers. If working with code, it's often recommended to split by meaningful code chunks for example using an Abstract Syntax Tree (AST) parser.

Create embeddings for each text chunk

For each text chunk, we then need to create text embeddings, which are numeric representations of the text in the vector space. Words with similar meanings are expected to be in closer proximity or have a shorter distance in the vector space. To create an embedding, use Mistral AI's embeddings API endpoint and the embedding model mistral-embed. We create a get_text_embedding to get the embedding from a single text chunk and then we use list comprehension to get text embeddings for all text chunks.

def get_text_embedding(input):
    embeddings_batch_response = client.embeddings.create(
          model="mistral-embed",
          inputs=input
      )
    return embeddings_batch_response.data[0].embedding
text_embeddings = np.array([get_text_embedding(chunk) for chunk in chunks])

Load into a vector database

Once we get the text embeddings, a common practice is to store them in a vector database for efficient processing and retrieval. There are several vector database to choose from. In our simple example, we are using an open-source vector database Faiss, which allows for efficient similarity search.

With Faiss, we instantiate an instance of the Index class, which defines the indexing structure of the vector database. We then add the text embeddings to this indexing structure.

import faiss

d = text_embeddings.shape[1]
index = faiss.IndexFlatL2(d)
index.add(text_embeddings)

Considerations:

    Vector database: When selecting a vector database, there are several factors to consider including speed, scalability, cloud management, advanced filtering, and open-source vs. closed-source.

Create embeddings for a question

Whenever users ask a question, we also need to create embeddings for this question using the same embedding models as before.

question = "What were the two main things the author worked on before college?"
question_embeddings = np.array([get_text_embedding(question)])

Considerations:

    Hypothetical Document Embeddings (HyDE): In some cases, the user's question might not be the most relevant query to use for identifying the relevant context. Instead, it maybe more effective to generate a hypothetical answer or a hypothetical document based on the user's query and use the embeddings of the generated text to retrieve similar text chunks.

Retrieve similar chunks from the vector database

We can perform a search on the vector database with index.search, which takes two arguments: the first is the vector of the question embeddings, and the second is the number of similar vectors to retrieve. This function returns the distances and the indices of the most similar vectors to the question vector in the vector database. Then based on the returned indices, we can retrieve the actual relevant text chunks that correspond to those indices.

D, I = index.search(question_embeddings, k=2) # distance, index
retrieved_chunk = [chunks[i] for i in I.tolist()[0]]

Considerations:

    Retrieval methods: There are a lot different retrieval strategies. In our example, we are showing a simple similarity search with embeddings. Sometimes when there is metadata available for the data, it's better to filter the data based on the metadata first before performing similarity search. There are also other statistical retrieval methods like TF-IDF and BM25 that use frequency and distribution of terms in the document to identify relevant text chunks.
    Retrieved document: Do we always retrieve individual text chunk as it is? Not always.
        Sometime, we would like to include more context around the actual retrieved text chunk. We call the actual retrieved text chunk "child chunk" and our goal is to retrieve a larger "parent chunk" that the "child chunk" belongs to.
        On occasion, we might also want to provide weights to our retrieve documents. For example, a time-weighted approach would help us retrieve the most recent document.
        One common issue in the retrieval process is the "lost in the middle" problem where the information in the middle of a long context gets lost. Our models have tried to mitigate this issue. For example, in the passkey task, our models have demonstrated the ability to find a "needle in a haystack" by retrieving a randomly inserted passkey within a long prompt, up to 32k context length. However, it is worth considering experimenting with reordering the document to determine if placing the most relevant chunks at the beginning and end leads to improved results.

Combine context and question in a prompt and generate response

Finally, we can offer the retrieved text chunks as the context information within the prompt. Here is a prompt template where we can include both the retrieved text and user question in the prompt.

prompt = f"""
Context information is below.
---------------------
{retrieved_chunk}
---------------------
Given the context information and not prior knowledge, answer the query.
Query: {question}
Answer:
"""

Then we can use the Mistral chat completion API to chat with a Mistral model (e.g., mistral-medium-latest) and generate answers based on the user question and the context of the question.

def run_mistral(user_message, model="mistral-large-latest"):
    messages = [
        {
            "role": "user", "content": user_message
        }
    ]
    chat_response = client.chat.complete(
        model=model,
        messages=messages
    )
    return (chat_response.choices[0].message.content)

run_mistral(prompt)

Output:

'The two main things the author worked on before college were writing and programming. They wrote short stories and tried writing programs on an IBM 1401 in 9th grade.'

Considerations:

    Prompting techniques: Most of the prompting techniques can be used in developing a RAG system as well. For example, we can use few-shot learning to guide the model's answers by providing a few examples. Additionally, we can explicitly instruct the model to format answers in a certain way.

RAG Examples

Find multiple RAG cookbooks exploring diverse topics and solutions in our community-driven cookbook.

Among them you can find how to perform...

    RAG with LangChain: Visit our community cookbook examples to discover how to use LangChain's LangGraph with the Mistral API. These cookbooks cover various implementations, including adaptive RAG, corrective RAG, and self-RAG, showcasing how to integrate LangChain's capabilities for enhanced retrieval-augmented generation.
    RAG with LlamaIndex: Visit our community cookbook example to learn how to use LlamaIndex with the Mistral API to perform complex queries over multiple documents using a ReAct agent, an autonomous LLM-powered agent capable of using tools.
    RAG with Haystack: Visit our community cookbook example to explore how to use Haystack with the Mistral API for chat functionalities with documents.






Text Embeddings
Open In Colab
Mistral Embed API

To generate text embeddings using Mistral AI's embeddings API, we can make a request to the API endpoint and specify the embedding model mistral-embed, along with providing a list of input texts. The API will then return the corresponding embeddings as numerical vectors, which can be used for further analysis or processing in NLP applications.

    python
    typescript
    curl

import os
from mistralai import Mistral

api_key = os.environ["MISTRAL_API_KEY"]
model = "mistral-embed"

client = Mistral(api_key=api_key)

embeddings_batch_response = client.embeddings.create(
    model=model,
    inputs=["Embed this sentence.", "As well as this one."],
)

The output embeddings_batch_response is an EmbeddingResponse object with the embeddings and the token usage information.

EmbeddingResponse(
    id='eb4c2c739780415bb3af4e47580318cc', object='list', data=[
        Data(object='embedding', embedding=[-0.0165863037109375,...], index=0),
        Data(object='embedding', embedding=[-0.0234222412109375,...], index=1)],
    model='mistral-embed', usage=EmbeddingResponseUsage(prompt_tokens=15, total_tokens=15)
)

Let's take a look at the length of the first embedding:

    python
    typescript
    curl

len(embeddings_batch_response.data[0].embedding)

It returns 1024, which means that our embedding dimension is 1024. The mistral-embed model generates embedding vectors of dimension 1024 for each text string, regardless of the text length. It's worth nothing that while higher dimensional embeddings can better capture text information and improve the performance of NLP tasks, they may require more computational resources for hosting and inference, and may result in increased latency and memory usage for storing and processing these embeddings. This trade-off between performance and computational resources should be considered when designing NLP systems that rely on text embeddings.
Distance Measures

In the realm of text embeddings, texts with similar meanings or context tend to be located in closer proximity to each other within this space, as measured by the distance between their vectors. This is due to the fact that the model has learned to group semantically related texts together during the training process.

Let's take a look at a simple example. To simplify working with text embeddings, we can wrap the embedding API in this function:

from sklearn.metrics.pairwise import euclidean_distances

def get_text_embedding(inputs):
    embeddings_batch_response = client.embeddings.create(
        model=model,
        inputs=inputs
    )
    return embeddings_batch_response.data[0].embedding

Suppose we have two sentences: one about cats and the other about books. We want to find how similar each sentence is to the reference sentence "Books are mirrors: You only see in them what you already have inside you". We can see that the distance between the reference sentence embeddings and the book sentence embeddings is smaller than the distance between the reference sentence embeddings and the cat sentence embeddings.

sentences = [
    "A home without a cat — and a well-fed, well-petted and properly revered cat — may be a perfect home, perhaps, but how can it prove title?",
    "I think books are like people, in the sense that they'll turn up in your life when you most need them"
]
embeddings = [get_text_embedding([t]) for t in sentences]

reference_sentence = "Books are mirrors: You only see in them what you already have inside you"
reference_embedding = get_text_embedding([reference_sentence])

for t, e in zip(sentences, embeddings):
    distance = euclidean_distances([e], [reference_embedding])
    print(t, distance)

Output

A home without a cat — and a well-fed, well-petted and properly revered cat — may be a perfect home, perhaps, but how can it prove title? [[0.80094257]]
I think books are like people, in the sense that they'll turn up in your life when you most need them [[0.58162089]]

In our example above, we used the Euclidean distance to measure the distance between embedding vectors (note that since Mistral AI embeddings are norm 1, cosine similarity, dot product or Euclidean distance are all equivalent).
Paraphrase detection

Another potential use case is paraphrase detection. In this simple example, we have a list of three sentences, and we would like to find out if any of the two sentences are paraphrases of each other. If the distance between two sentence embeddings is small, it suggests that the two sentences are semantically similar and could be potential paraphrases.

The result suggests that the first two sentences are semantically similar and could be potential paraphrases, whereas the third sentence is more different. This is just a super simple example. But this approach can be extended to more complex situations in real-world applications, such as detecting paraphrases in social media posts, news articles, or customer reviews.

import itertools

sentences = [
    "Have a safe happy Memorial Day weekend everyone",
    "To all our friends at Whatsit Productions Films enjoy a safe happy Memorial Day weekend",
    "Where can I find the best cheese?",
]

sentence_embeddings = [get_text_embedding([t]) for t in sentences]

sentence_embeddings_pairs = list(itertools.combinations(sentence_embeddings, 2))
sentence_pairs = list(itertools.combinations(sentences, 2))
for s, e in zip(sentence_pairs, sentence_embeddings_pairs):
    print(s, euclidean_distances([e[0]], [e[1]]))

Output

('Have a safe happy Memorial Day weekend everyone', 'To all our friends at Whatsit Productions Films enjoy a safe happy Memorial Day weekend') [[0.54326686]]
('Have a safe happy Memorial Day weekend everyone', 'Where can I find the best cheese?') [[0.92573978]]
('To all our friends at Whatsit Productions Films enjoy a safe happy Memorial Day weekend', 'Where can I find the best cheese?') [[0.9114184]]

Batch processing

The Mistral AI Embeddings API is designed to process text in batches for improved efficiency and speed. In this example, we will demonstrate this by loading the Symptom2Disease dataset from Kaggle, which contains 1200 rows with two columns: "label" and "text". The "label" column indicates the disease category, while the "text" column describes the symptoms associated with that disease.

We wrote a function get_embeddings_by_chunks that splits data into chunks and then sends each chunk to the Mistral AI Embeddings API to get the embeddings. Then we saved the embeddings as a new column in the dataframe. Note that the API will provide auto-chunking in the future, so that users don't need to manually split the data into chunks before sending it.

import pandas as pd

df = pd.read_csv(
    "https://raw.githubusercontent.com/mistralai/cookbook/main/data/Symptom2Disease.csv",
    index_col=0,
)

def get_embeddings_by_chunks(data, chunk_size):
    chunks = [data[x : x + chunk_size] for x in range(0, len(data), chunk_size)]
    embeddings_response = [
        client.embeddings.create(model=model, inputs=c) for c in chunks
    ]
    return [d.embedding for e in embeddings_response for d in e.data]

df["embeddings"] = get_embeddings_by_chunks(df["text"].tolist(), 50)
df.head()

drawing
t-SNE embeddings visualization

We mentioned previously that our embeddings have 1024 dimensions, which makes them impossible to visualize directly. Thus, in order to visualize our embeddings, we can use a dimensionality reduction technique such as t-SNE to project our embeddings into a lower-dimensional space that is easier to visualize.

In this example, we transform our embeddings to 2 dimensions and create a 2D scatter plot showing the relationships among embeddings of different diseases.

import seaborn as sns
from sklearn.manifold import TSNE
import numpy as np

tsne = TSNE(n_components=2, random_state=0).fit_transform(np.array(df['embeddings'].to_list()))
ax = sns.scatterplot(x=tsne[:, 0], y=tsne[:, 1], hue=np.array(df['label'].to_list()))
sns.move_legend(ax, 'upper left', bbox_to_anchor=(1, 1))

drawing
Comparison with fastText

We can compare it with fastText, a popular open-source embeddings model. However, when examining the t-SNE embeddings plot, we notice that fastText embeddings fail to create clear separations between data points with matching labels.

import fasttext.util

fasttext.util.download_model('en', if_exists='ignore')  # English
ft = fasttext.load_model('cc.en.300.bin')

df['fasttext_embeddings'] = df['text'].apply(lambda x: ft.get_word_vector(x).tolist())

tsne = TSNE(n_components=2, random_state=0).fit_transform(np.array(df['fasttext_embeddings'].to_list()))
ax = sns.scatterplot(x=tsne[:, 0], y=tsne[:, 1], hue=np.array(df['label'].to_list()))
sns.move_legend(ax, 'upper left', bbox_to_anchor=(1, 1))

drawing
Classification

Text embeddings can be used as input features in machine learning models, such as classification and clustering. In this example, we use a classification model to predict the disease labels from the embeddings of disease description text.

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

# Create a train / test split
train_x, test_x, train_y, test_y = train_test_split(
    df["embeddings"], df["label"], test_size=0.2
)

# Normalize features
scaler = StandardScaler()
train_x = scaler.fit_transform(train_x.to_list())
test_x = scaler.transform(test_x.to_list())

# Train a classifier and compute the test accuracy
# For a real problem, C should be properly cross validated and the confusion matrix analyzed
clf = LogisticRegression(random_state=0, C=1.0, max_iter=500).fit(
    train_x, train_y.to_list()
)
# you can also try the sag algorithm:
# clf = LogisticRegression(random_state=0, C=1.0, max_iter=1000, solver='sag').fit(train_x, train_y)

print(f"Precision: {100*np.mean(clf.predict(test_x) == test_y.to_list()):.2f}%")

Output

Precision: 98.75%

After we trained the classifier with our embeddings data, we can try classify other text:

# Classify a single example
text = "I've been experiencing frequent headaches and vision problems."
clf.predict([get_text_embedding([text])])

Output

'Migraine'

Comparison with fastText

Additionally, let's take a look at the performance using fastText embeddings in this classification task. It appears that the classification model achieves better performance with Mistral AI Embeddings model as compared to using fastText embeddings.

# Create a train / test split
train_x, test_x, train_y, test_y = train_test_split(
    df["fasttext_embeddings"], df["label"], test_size=0.2
)

# Normalize features
scaler = StandardScaler()
train_x = scaler.fit_transform(train_x.to_list())
test_x = scaler.transform(test_x.to_list())

# Train a classifier and compute the test accuracy
# For a real problem, C should be properly cross validated and the confusion matrix analyzed
clf = LogisticRegression(random_state=0, C=1.0, max_iter=500).fit(
    train_x, train_y.to_list()
)
# you can also try the sag algorithm:
# clf = LogisticRegression(random_state=0, C=1.0, max_iter=1000, solver='sag').fit(train_x, train_y)

print(f"Precision: {100*np.mean(clf.predict(test_x) == test_y.to_list()):.2f}%")

Output

Precision: 86.25%

Clustering

What if we don't have disease labels? One approach to gain insights from the data is through clustering. Clustering is an unsupervised machine learning technique that groups similar data points together based on their similarity with respect to certain features. In the context of text embeddings, we can use the distance between each embedding as a measure of similarity, and group together data points with embeddings that are close to each other in the high-dimensional space.

Since we already know there are 24 clusters, let's use the K-means clustering with 24 clusters. Then we can inspect a few examples and verify whether the examples in a single cluster are similar to one another. For example, take a look at the first three rows of cluster 23. We can see that they look very similar in terms of symptoms.

from sklearn.cluster import KMeans

model = KMeans(n_clusters=24, max_iter=1000)
model.fit(df['embeddings'].to_list())
df["cluster"] = model.labels_
print(*df[df.cluster==23].text.head(3), sep='\n\n')

Output:

I have been feeling extremely tired and weak, and I've also been coughing a lot with difficulty breathing. My fever is very high, and I'm producing a lot of mucus when I cough.
I've got a cough that won't go away, and I'm exhausted. I've been coughing up thick mucous and my fever is also pretty high.
I have a persistent cough and have been feeling quite fatigued. My fever is through the roof, and I'm having trouble breathing. When I cough, I also cough up a lot of mucous.

Retrieval
Our embedding model excels in retrieval tasks, as it is trained with retrieval in mind. Embeddings are also incredibly helpful in implementing retrieval-augmented generation (RAG) systems, which use retrieved relevant information from a knowledge base to generate responses. At a high-level, we embed a knowledge base, whether it is a local directory, text files, or internal wikis, into text embeddings and store them in a vector database. Then, based on the user's query, we retrieve the most similar embeddings, which represent the relevant information from the knowledge base. Finally, we feed these relevant embeddings to a large language model to generate a response that is tailored to the user's query and context. If you are interested in learning more about how RAG systems work and how to implement a basic RAG, check out our previous guide on this topic.