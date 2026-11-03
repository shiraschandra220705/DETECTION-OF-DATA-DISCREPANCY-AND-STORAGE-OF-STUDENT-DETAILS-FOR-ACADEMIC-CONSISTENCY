
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from fuzzywuzzy import fuzz
import joblib
import os
import pandas as pd
import pandas as pd

# read specific columns of csv file using Pandas
data = pd.read_csv("Student_Details.csv", usecols=['Name', 'USN', 'DOB', 'CGPA', 'Semester', '10th Percentage', '12th Percentage', 'Branch'])

df = pd.DataFrame(data)
def get_model():
    model_path = 'tfidf_vectorizer.pkl'
    if os.path.exists(model_path):
        vectorizer = joblib.load(model_path)
    else:
        vectorizer = TfidfVectorizer(ngram_range=(1, 3)) 
        vectorizer.fit(df['Name'])
        joblib.dump(vectorizer, model_path)

    return vectorizer



def search_thing(keyword, fuzzy_threshold=40):
    
    vectorizer = get_model()
    keyword_name, keyword_usn, keyword_dob, keyword_cgpa, keyword_sem, keyword_tenth, keyword_puc, keyword_branch = keyword.split(',')
    keyword_cgpa = float(keyword_cgpa)
    keyword_sem1 = str(keyword_sem)
    keyword_tenth = f"{float(keyword_tenth):.1f}"
    keyword_puc = f"{float(keyword_puc):.1f}"

    keyword_vector_name = vectorizer.transform([keyword_name])
    
    tfidf_matrix_name = vectorizer.transform(df['Name'])
    cosine_similarities_name = cosine_similarity(keyword_vector_name, tfidf_matrix_name).flatten()
    
    df['similarity_score'] = cosine_similarities_name
    
    if df['similarity_score'].max() < 0.1:
        
        fuzzy_name = df['Name'].apply(lambda x: fuzz.partial_ratio(keyword_name, x))
        fuzzy_usn = df['USN'].apply(lambda x: fuzz.partial_ratio(keyword_usn, x))
        fuzzy_dob = df['DOB'].apply(lambda x: fuzz.partial_ratio(keyword_dob, x))
        fuzzy_cgpa = df['CGPA'].apply(lambda x: max(0, (1 - abs(keyword_cgpa - x) / 4.0) * 100))
        fuzzy_sem = df['Semester'].apply(lambda x: fuzz.partial_ratio(keyword_sem1, str(int(x))) if pd.notnull(x) else 0)
        fuzzy_tenth = df['10th Percentage'].apply(lambda x: fuzz.partial_ratio(keyword_tenth, f"{float(x):.1f}") if pd.notnull(x) else 0)        
        fuzzy_twelfth = df['10th Percentage'].apply(lambda x: fuzz.partial_ratio(keyword_puc, f"{float(x):.1f}") if pd.notnull(x) else 0)
        fuzzy_branch = df['Branch'].apply(lambda x: fuzz.partial_ratio(keyword_branch, x))


        df['fuzzy_score'] = (fuzzy_name + fuzzy_usn + fuzzy_dob + fuzzy_cgpa + fuzzy_sem + fuzzy_twelfth + fuzzy_tenth + fuzzy_branch)/8
        
        related_articles = df[df['fuzzy_score'] > fuzzy_threshold].sort_values(by='fuzzy_score', ascending=False)
        return related_articles[['USN', 'DOB','Name', 'Semester', '10th Percentage', '12th Percentage','Branch', 'fuzzy_score']]
    related_indices = cosine_similarities_name.argsort()[::-1]
    related_articles = df.iloc[related_indices]
    return related_articles[['USN', 'DOB','Name', 'Semester', '10th Percentage', '12th Percentage','Branch', 'similarity_score']]

keyword = input("Enter Name, USN, Date of Birth (in DD/MM/YYYY format), CGPA, Semester, 10th percentage, 12th percentage and Branch")
result = search_thing(keyword)
print(result.to_string(index=False))
