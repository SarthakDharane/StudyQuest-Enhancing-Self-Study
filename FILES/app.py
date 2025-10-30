import google.generativeai as genai
import requests
import json
import pandas as pd
import re
from datetime import datetime,timedelta
import matplotlib.pyplot as plt
import threading
import time
from flask import Flask, request, jsonify, render_template,session,url_for,redirect

# Flask App Initialization
app = Flask(__name__)
app.secret_key = "n.e.r.v" 
# API Configuration
GEMINI_API_KEY = "AIzaSyBnq6BEFnsswRNBbu1Sw38Be7XT9amt3L0"
YOUTUBE_API_KEY = "AIzaSyD5qzngZoGlq4MwYE9vcTEBv6YEw0gxylY"

genai.configure(api_key=GEMINI_API_KEY)

# Global Variables for User Progress Tracking
user_scores = []
user_score = 0
user_exp = 0
user_level = 1
user_schedule = []

def update_progress(exp_gained, score_gained=0):
    """Update user's experience, level, and score based on activity"""
    global user_score, user_exp, user_level
    
    # Update experience and score
    user_exp += exp_gained
    user_score += score_gained
    
    # Level-up system based on EXP thresholds
    if user_exp >= 1000:
        user_level = 5
    elif user_exp >= 700:
        user_level = 4
    elif user_exp >= 400:
        user_level = 3
    elif user_exp >= 200:
        user_level = 2
    else:
        user_level = 1

def get_best_playlist(topic, language):
    """Find the best YouTube playlist for a given topic and language"""
    search_query = f"{topic} {language} tutorial"
    url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={search_query}&type=playlist&maxResults=1&key={YOUTUBE_API_KEY}"
    
    response = requests.get(url).json()
    
    if "items" in response and response["items"]:
        item = response["items"][0]
        playlist_id = item["id"]["playlistId"]
        title = item["snippet"]["title"]
        return {
            "title": title, 
            "url": f"https://www.youtube.com/embed/videoseries?list={playlist_id}",
            "playlist_id": playlist_id
        }
    
    return {"error": "No playlist found"}

def get_videos_from_playlist(playlist_id):
    """Retrieve videos from a YouTube playlist"""
    url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&playlistId={playlist_id}&maxResults=5&key={YOUTUBE_API_KEY}"
    response = requests.get(url).json()
    
    videos = []
    if "items" in response:
        for item in response["items"]:
            video_id = item["snippet"]["resourceId"]["videoId"]
            title = item["snippet"]["title"]
            description = item["snippet"]["description"]
            videos.append({"video_id": video_id, "title": title, "description": description})
    
    return videos

def generate_mcqs(video):
    """Generate multiple-choice questions based on video content"""
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    prompt = f"""
    Based on the YouTube video titled: "{video['title']}" with description: 
    "{video['description']}", generate 5 multiple-choice questions (MCQs).
    
    Each question should have 4 options and indicate the correct answer.

    Format the response in JSON:
    [
        {{
            "question": "What is AI?",
            "options": ["A technology", "A fruit", "A car", "A book"],
            "correct_answer": "A technology"
        }},
        ...
    ]
    """

    response = model.generate_content(prompt)

    try:
        return json.loads(response.text.strip())
    except json.JSONDecodeError:
        return [{"question": "Error generating MCQs", "options": [], "correct_answer": ""}]

def evaluate_answers(user_answers, correct_answers):
    """Evaluate user answers against correct answers"""
    global user_scores
    
    score = sum(1 for user_ans, correct_ans in zip(user_answers, correct_answers) if user_ans == correct_ans)
    user_scores.append(score)

    return {
        "score": score, 
        "total_questions": len(correct_answers),
        "loop_video": (score == 0)
    }

def generate_graph():
    """Generate a progress graph based on user scores"""
    df = pd.DataFrame({"Video Number": list(range(1, len(user_scores) + 1)), "Marks Obtained": user_scores})
    plt.figure(figsize=(8, 5))
    plt.bar(df["Video Number"], df["Marks Obtained"], color="blue")
    plt.xlabel("Video Number")
    plt.ylabel("Marks Obtained")
    plt.title("Learning Progress")
    plt.savefig("static/progress.png")

def parse_json_response(raw_response):
    """Parse JSON response from Gemini, with fallback using regex"""
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError:
        try:
            match = re.search(r'\[\s*{.*?}\s*\]', raw_response, re.DOTALL)
            if match:
                return json.loads(match.group())
            else:
                return [{"error": "No JSON array found in response"}]
        except Exception as e:
            return [{"error": f"Error parsing JSON: {str(e)}"}]

def track_time():
    if "start_time" not in session:
        session["start_time"] = datetime.now().isoformat()

focus_mode_active = False
focus_mode_start_time = None
suppressed_notifications = []

# Auto-timeout thread
def auto_timeout_checker():
    global focus_mode_active, focus_mode_start_time
    
    while True:
        if focus_mode_active and focus_mode_start_time:
            current_time = datetime.now()
            elapsed_time = (current_time - focus_mode_start_time).total_seconds()
            
            # If focus mode has been active for more than 1 hour, turn it off
            if elapsed_time >= 3600:  # 1 hour = 3600 seconds
                focus_mode_active = False
                focus_mode_start_time = None
                print("Focus mode automatically deactivated after 1 hour")
                
                # Make all suppressed notifications available
                for notification in suppressed_notifications:
                    notification['is_suppressed'] = False
        
        # Check every 30 seconds
        time.sleep(30)

# Start the auto-timeout thread
timeout_thread = threading.Thread(target=auto_timeout_checker, daemon=True)
timeout_thread.start()


@app.route("/focus")
def focus_page():
    """Render the focus mode page"""
    return render_template("focus.html", user_exp=user_exp, user_level=user_level, user_score=user_score)

# Toggle focus mode on/off
@app.route('/api/focus-mode/toggle', methods=['POST'])
def toggle_focus_mode():
    global focus_mode_active, focus_mode_start_time
    
    # Toggle the focus mode
    focus_mode_active = not focus_mode_active
    
    if focus_mode_active:
        # If turning on, set the start time
        focus_mode_start_time = datetime.now()
        message = "Focus mode activated"
        auto_off_time = (focus_mode_start_time + timedelta(hours=1)).strftime("%H:%M:%S")
    else:
        # If turning off, clear start time and unsuppress notifications
        focus_mode_start_time = None
        message = "Focus mode deactivated"
        auto_off_time = None
        
        # Make all suppressed notifications available
        for notification in suppressed_notifications:
            notification['is_suppressed'] = False
    
    return jsonify({
        'success': True,
        'is_active': focus_mode_active,
        'message': message,
        'auto_off_time': auto_off_time
    })

# Get current focus mode status
@app.route('/api/focus-mode/status', methods=['GET'])
def get_focus_mode_status():
    remaining_seconds = 0
    auto_off_time = None
    
    if focus_mode_active and focus_mode_start_time:
        current_time = datetime.now()
        elapsed_seconds = (current_time - focus_mode_start_time).total_seconds()
        remaining_seconds = max(0, 3600 - elapsed_seconds)  # 1 hour = 3600 seconds
        auto_off_time = (focus_mode_start_time + timedelta(hours=1)).strftime("%H:%M:%S")
    
    return jsonify({
        'is_active': focus_mode_active,
        'remaining_seconds': int(remaining_seconds),
        'remaining_minutes': round(remaining_seconds / 60, 1),
        'auto_off_time': auto_off_time
    })

# Create a new notification
@app.route('/api/notifications/create', methods=['POST'])
def create_notification():
    data = request.get_json()
    content = data.get('content')
    
    if not content:
        return jsonify({'error': 'Notification content is required'}), 400
    
    # Create the notification
    notification = {
        'id': len(suppressed_notifications) + 1,
        'content': content,
        'is_suppressed': focus_mode_active,
        'created_at': datetime.now().strftime("%H:%M:%S")
    }
    
    # If focus mode is active, add to suppressed list
    if focus_mode_active:
        suppressed_notifications.append(notification)
        return jsonify({
            'success': True,
            'message': 'Notification suppressed due to active focus mode',
            'notification': notification
        })
    
    # Otherwise return it normally
    return jsonify({
        'success': True,
        'message': 'Notification created',
        'notification': notification
    })

# Get all notifications
@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    include_suppressed = request.args.get('include_suppressed', 'false').lower() == 'true'
    
    if include_suppressed:
        # Return all notifications
        return jsonify({'notifications': suppressed_notifications})
    else:
        # Return only unsuppressed notifications
        unsuppressed = [n for n in suppressed_notifications if not n['is_suppressed']]
        return jsonify({'notifications': unsuppressed})

# Get suppressed notifications only
@app.route('/api/notifications/suppressed', methods=['GET'])
def get_suppressed_notifications():
    suppressed = [n for n in suppressed_notifications if n['is_suppressed']]
    return jsonify({'notifications': suppressed})

@app.route("/")
def index1():
    return render_template("index1.html")

@app.route("/home")
def home():
    if "start_time" not in session:
        session["start_time"] = datetime.now().isoformat()

    start_time = datetime.fromisoformat(session["start_time"])
    total_time = datetime.now() - start_time
    total_seconds = int(total_time.total_seconds())

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    formatted_time = f"{hours} hr {minutes} min {seconds} sec"

    return render_template(
        "home.html",
        user_exp=user_exp,
        user_level=user_level,
        user_score=user_score,
        time_spent=formatted_time
    )

@app.route("/self")
def self_study():
    return render_template("index.html", user_exp=user_exp, user_level=user_level, user_score=user_score)

@app.route("/get_playlist", methods=["POST"])
def fetch_playlist():
    data = request.json
    playlist = get_best_playlist(data["topic"], data["language"])
    
    if "error" in playlist:
        return jsonify(playlist)

    videos = get_videos_from_playlist(playlist["playlist_id"])
    playlist["videos"] = videos
    
    # Award EXP for finding learning resources
    update_progress(10)
    
    return jsonify(playlist)

@app.route("/get_mcqs", methods=["POST"])
def fetch_mcqs():
    data = request.json
    video = data["video"]
    
    mcqs = generate_mcqs(video)
    return jsonify(mcqs)

@app.route("/evaluate", methods=["POST"])
def evaluate_endpoint():
    data = request.json
    feedback = evaluate_answers(data["user_answers"], data["correct_answers"])

    if not feedback["loop_video"]:
        generate_graph()
        # Award EXP and score for completed quiz
        update_progress(50, feedback["score"] * 10)  # 50 EXP and 10 points per correct answer

    return jsonify({
        **feedback,
        "experience": user_exp,
        "level": user_level,
        "score": user_score
    })

@app.route("/chatbot", methods=["POST"])
def chatbot_api():
    data = request.json
    user_message = data.get("message")

    if not user_message:
        return jsonify({"response": "Please ask a valid question."})

    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = f"Explain in detail and format it properly with bold, spaces, and line breaks for clarity: {user_message}"
    response = model.generate_content(prompt)

    # Award EXP for using the chatbot
    update_progress(5)
    
    return jsonify({"response": response.text})


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("email")
        password = request.form.get("password")

        if username == "john@nerv.com" and password == "Smith123":
            session["username"] = username  # optional if you want to use it later
            return redirect(url_for('home'))   # ← now goes to /home
        else:
            error = "🧙 Invalid scroll or incantation! Try again, brave scholar."
    
    return render_template("login.html", error=error)

@app.route("/bell")
def bell():
    return render_template("notification.html")

@app.route("/chatbot")
def chat_page():
    return render_template("chatbot.html", user_exp=user_exp, user_level=user_level, user_score=user_score)

@app.route("/challenge")
def challenge():
    progress_percent = (user_exp / 1000) * 100  # Based on max level (level 5 = 1000 XP)
    return render_template("challenge.html", user_exp=user_exp, user_level=user_level, 
                          user_score=user_score, progress_percent=progress_percent)

@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if request.method == "POST":
        # Collect feedback data
        name = request.form.get("name")
        email = request.form.get("email")
        message = request.form.get("message")
        content_quality = request.form.get("content_quality")
        engagement = request.form.get("engagement")
        improvement_suggestion = request.form.get("improvement_suggestion")
        overall_rating = request.form.get("overall_rating")

        print(f"""
        📋 Parental Feedback Received:
        Name: {name}
        Email: {email}
        Message: {message}
        Content Quality: {content_quality}
        Engagement Level: {engagement}
        Suggestion: {improvement_suggestion}
        Rating: {overall_rating}/5
        """)
        
        # Award EXP for providing feedback
        update_progress(15)

        return render_template("feedback.html", success=True, user_exp=user_exp, 
                              user_level=user_level, user_score=user_score)

    return render_template("feedback.html", success=False, user_exp=user_exp, 
                          user_level=user_level, user_score=user_score)

@app.route("/quiz", methods=["GET"])
def show_quiz_page():
    return render_template("quiz.html", user_exp=user_exp, user_level=user_level, user_score=user_score)

@app.route("/generate_quiz", methods=["POST"])
def generate_quiz():
    data = request.json
    topic = data.get("topic")

    if not topic:
        return jsonify({"error": "Topic is required."})

    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""
    Generate 10 multiple-choice questions (MCQs) on the topic "{topic}".
    Each question should have:
    - 4 answer options
    - One correct answer clearly marked.

    Format your response strictly in JSON like this:
    [
        {{
            "question": "What is DSA?",
            "options": ["Data Structures and Algorithms", "Digital Signal Analysis", "Dynamic Storage Access", "None"],
            "correct_answer": "Data Structures and Algorithms"
        }},
        ...
    ]
    """

    response = model.generate_content(prompt)
    raw_response = response.text.strip()
    
    quiz_mcqs = parse_json_response(raw_response)
    
    # Award EXP and points for generating a quiz
    update_progress(20, 5)
    
    return jsonify({
        "topic": topic,
        "quiz_mcqs": quiz_mcqs,
        "user_exp": user_exp,
        "user_level": user_level, 
        "user_score": user_score
    })

@app.route("/schedule", methods=["GET"])
def schedule_page():
    return render_template("schedule.html", user_exp=user_exp, user_level=user_level, user_score=user_score)

@app.route("/generate_schedule", methods=["POST"])
def generate_schedule():
    data = request.json
    topic = data.get("topic")
    start_time = data.get("start_time")
    end_time = data.get("end_time")

    if not topic or not start_time or not end_time:
        return jsonify({"error": "Topic, start_time, and end_time are required."})

    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""
You are a smart study planner bot.

Your goal is to generate a **progressive concept-wise study schedule** for the topic: "{topic}", between {start_time} and {end_time} (24-hour format).

Step 1: Analyze the topic "{topic}" and identify 6–10 important subtopics or concepts, ordered from basic to advanced.

Step 2: Divide the time range ({start_time} to {end_time}) into logical study slots. Each time slot should focus on **one subtopic** from Step 1.

Step 3: Add short breaks (5–15 minutes) after every 1–2 study blocks to improve productivity.

🟡 Output Format:
Return ONLY in this **strict JSON format**:
[
  {{
    "time": "HH:MM - HH:MM",
    "activity": "Subtopic name or Short Break"
  }},
  ...
]

🟡 Examples of 'activity':
"Basics of Machine Learning", "Stacks and Queues", "Short Break", "Data Preprocessing in ML", etc.

❌ Do NOT add any explanation or extra text. Return only the JSON array.
Act like an expert subject matter educator and study schedule designer.

    """

    response = model.generate_content(prompt)
    raw_response = response.text.strip()
    
    schedule = parse_json_response(raw_response)
    
    # Award EXP and points for creating a schedule
    update_progress(30, 15)
    
    return jsonify({
        "topic": topic,
        "start_time": start_time,
        "end_time": end_time,
        "schedule": schedule,
        "experience": user_exp,
        "level": user_level,
        "score": user_score
    })

@app.route('/search_courses', methods=['POST'])
def search_courses():
    model = genai.GenerativeModel("gemini-2.0-flash")
    topic = request.form['topic']
    prompt = f"""Suggest 3 best online links free courses (nptel,udacity) for the topic '{topic}'.
Each course should include:
- Title
- Short description
- Duration in hours
- Rating out of 5
- Difficulty level (Beginner, Intermediate, Advanced)

Format output like:
Course 1:
Title: ...
Description: ...
Duration: ...
Rating: ...
Level: ...

Course 2:
...
"""
    response = model.generate_content(prompt)
    raw_text = response.text

    # Basic parsing (you can refine this if needed)
    course_blocks = raw_text.strip().split("Course")
    parsed_courses = []

    for block in course_blocks:
        if "Title:" in block:
            lines = block.strip().split('\n')
            course = {}
            for line in lines:
                if line.startswith("Title:"):
                    course["title"] = line.replace("Title:", "").strip()
                elif line.startswith("Description:"):
                    course["description"] = line.replace("Description:", "").strip()
                elif line.startswith("Duration:"):
                    course["duration"] = line.replace("Duration:", "").strip()
                elif line.startswith("Rating:"):
                    course["rating"] = line.replace("Rating:", "").strip()
                elif line.startswith("Level:"):
                    course["level"] = line.replace("Level:", "").strip()
            parsed_courses.append(course)

    return render_template('courses.html', courses=parsed_courses, topic=topic)

@app.route("/my_schedule", methods=["GET", "POST"])
def my_schedule():
    global user_schedule
    if "start_time" not in session:
        session["start_time"] = datetime.now().isoformat()

    start_time = datetime.fromisoformat(session["start_time"])
    total_time = datetime.now() - start_time
    total_seconds = int(total_time.total_seconds())

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    formatted_time = f"{hours} hr {minutes} min {seconds} sec"
    if request.method == "POST":
        if "add_task" in request.form:
            time = request.form.get("time")
            task = request.form.get("task")
            if time and task:
                user_schedule.append({"time": time, "task": task, "completed": False})
                # Award EXP for adding a task
                update_progress(2)
        
        elif "mark_done" in request.form:
            index = int(request.form.get("task_index"))
            if 0 <= index < len(user_schedule):
                if not user_schedule[index]["completed"]:
                    user_schedule[index]["completed"] = True
                    # Award EXP for completing a task
                    update_progress(10, 2)

    return render_template("my_schedule.html", schedule=user_schedule, 
                          user_exp=user_exp, user_level=user_level, user_score=user_score,time_spent=formatted_time)

@app.route("/st_pl")
def study_plan():
    return render_template("study_plan.html", user_exp=user_exp, user_level=user_level, user_score=user_score)

@app.route("/teachers", methods=["GET"])
def teachers():
    return render_template("teachers.html", user_exp=user_exp, user_level=user_level, user_score=user_score)

@app.route("/track", methods=["GET"])
def track():
    if "start_time" not in session:
        session["start_time"] = datetime.now().isoformat()

    start_time = datetime.fromisoformat(session["start_time"])
    total_time = datetime.now() - start_time
    total_seconds = int(total_time.total_seconds())

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    formatted_time = f"{hours} hr {minutes} min {seconds} sec"
    return render_template("track.html", user_exp=user_exp, user_level=user_level, user_score=user_score,time_spent=formatted_time)

if __name__ == "__main__":
    app.run(debug=True)