import os
import subprocess
from dotenv import load_dotenv
from openai import OpenAI
from flask import Flask, request, render_template_string, session
from werkzeug.utils import secure_filename
import PyPDF2
import markdown2

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Required for session management

# Get the OpenAI API key from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("No OpenAI API key found. Please set the OPENAI_API_KEY in your .env file.")

# Initialize the OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'pptx'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path):
    with open(file_path, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
    return text

# ... [rest of the code remains unchanged until the cross_question function] ...
def process_notes(notes):
    # Generate summary
    summary_response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that summarizes class notes. Provide the summary in Markdown format."},
            {"role": "user", "content": f"Please summarize these class notes:\n\n{notes}"}
        ]
    )
    summary = summary_response.choices[0].message.content

    # Generate questions
    questions_response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that creates exam questions based on class notes. Provide the questions in Markdown format."},
            {"role": "user", "content": f"Based on these class notes, generate 5 potential exam questions:\n\n{notes}"}
        ]
    )
    questions = questions_response.choices[0].message.content

    return {"summary": summary, "questions": questions, "full_text": notes}

@app.route('/', methods=['GET'])
def index():
    html = '''
    <!doctype html>
    <html>
    <head>
        <title>Notes Processor</title>
    </head>
    <body>
        <h1>Upload your notes (PDF or PPTX)</h1>
        <form action="/upload_files" method="post" enctype="multipart/form-data">
            <input type="file" name="files" accept=".pdf,.pptx" multiple>
            <input type="submit" value="Upload and Process">
        </form>
    </body>
    </html>
    '''
    return render_template_string(html)

@app.route('/upload_files', methods=['POST'])
def upload_files():
    if 'files' not in request.files:
        return "No file part"
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return "No selected files"

    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

    results = []
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        if filename.lower().endswith('.pdf'):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            # Extract text from PDF
            text = extract_text_from_pdf(file_path)

            # Process the extracted text
            result = process_notes(text)
            results.append({"filename": filename, "result": result})

    # Convert Markdown to HTML for all results
    for result in results:
        result['result']['summary_html'] = markdown2.markdown(result['result']['summary'])
        result['result']['questions_html'] = markdown2.markdown(result['result']['questions'])

    # Store results in session for later use
    session['results'] = results

    # Return the results as formatted HTML
    html_content = '''
    <!doctype html>
    <html>
    <head>
        <title>Processed Notes</title>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; }
            h1, h2, h3 { color: #333; }
            .file-result { margin-bottom: 40px; border-bottom: 1px solid #ccc; padding-bottom: 20px; }
            .cross-question-form { margin-top: 20px; }
            .cross-question-form textarea { width: 100%; height: 100px; }
        </style>
    </head>
    <body>
        <h1>Processed Notes</h1>
        {% for result in results %}
            <div class="file-result">
                <h2>{{ result['filename'] }}</h2>
                <h3>Summary:</h3>
                {{ result['result']['summary_html'] | safe }}
                <h3>Questions:</h3>
                {{ result['result']['questions_html'] | safe }}
                <div class="cross-question-form">
                    <h3>Ask a follow-up question:</h3>
                    <form action="/cross_question" method="post">
                        <input type="hidden" name="file_index" value="{{ loop.index0 }}">
                        <textarea name="question" placeholder="Enter your question here..."></textarea>
                        <br>
                        <input type="submit" value="Ask">
                    </form>
                </div>
            </div>
        {% endfor %}
    </body>
    </html>
    '''
    return render_template_string(html_content, results=results)



@app.route('/cross_question', methods=['POST'])
def cross_question():
    file_index = int(request.form['file_index'])
    question = request.form['question']
    results = session.get('results', [])

    if file_index < len(results):
        full_text = results[file_index]['result']['full_text']
        filename = results[file_index]['filename']

        # Generate answer using OpenAI with improved prompt
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": """You are an expert computer science professor known for your ability to explain complex topics clearly and concisely. Your task is to answer the student's question based on the provided class notes. In your response:
                1. Directly address the question asked.
                2. Provide a clear and concise explanation, using examples or analogies if helpful.
                3. If relevant, mention any related concepts from the notes that provide additional context.
                4. If the question cannot be fully answered based on the given notes, state this clearly and provide the best possible answer with the available information.
                5. Use Markdown formatting to structure your response, including code blocks for any code or pseudocode if applicable."},
                {"role": "user", "content": f"Based on the following class notes, please answer this question: {question}\n\nClass notes:\n{full_text}"""}
            ]
        )
        answer = response.choices[0].message.content
        # Convert answer to HTML
        if answer is not None:
            answer_html = markdown2.markdown(answer)
        else:
            answer_html = "<p>No answer available.</p>"

        # Prepare HTML response
        html_content = f'''
        <!doctype html>
        <html>
        <head>
            <title>Cross-Question Answer</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; }}
                h1, h2, h3 {{ color: #333; }}
                pre {{ background-color: #f4f4f4; padding: 10px; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <h1>Cross-Question Answer</h1>
            <h2>File: {filename}</h2>
            <h3>Question:</h3>
            <p>{question}</p>
            <h3>Answer:</h3>
            {answer_html}
            <br>
            <a href="/">Back to main page</a>
        </body>
        </html>
        '''
        return render_template_string(html_content)
    else:
        return "File not found", 404

if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.run(debug=True)
