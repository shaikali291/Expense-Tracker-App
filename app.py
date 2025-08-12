from flask import Flask, render_template, request, redirect, url_for, session, g, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, json, datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, 'data.db')

app = Flask(__name__)
app.secret_key = 'replace_this_with_a_random_secret'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    password TEXT
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS income (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount REAL,
                    category TEXT,
                    date TEXT,
                    note TEXT
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS expense (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount REAL,
                    category TEXT,
                    date TEXT,
                    note TEXT
                 )''')
    conn.commit()
    conn.close()

init_db()

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        username = request.form['username']
        password = request.form['password']
        hashed = generate_password_hash(password)
        try:
            conn = get_db(); c = conn.cursor()
            c.execute("INSERT INTO users (username,password) VALUES (?,?)", (username, hashed))
            conn.commit()
            flash('Account created. Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already taken.', 'danger')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        username = request.form['username']; password = request.form['password']
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=?", (username,))
        user = c.fetchone(); conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']; session['username'] = user['username']
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Helpers
def totals_and_monthly(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(amount),0) as total FROM income WHERE user_id=?", (user_id,))
    total_income = c.fetchone()['total']
    c.execute("SELECT COALESCE(SUM(amount),0) as total FROM expense WHERE user_id=?", (user_id,))
    total_expense = c.fetchone()['total']
    # Monthly aggregation for last 6 months
    today = datetime.date.today()
    labels = []
    inc_data = []; exp_data = []
    for i in range(5, -1, -1):
        m = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)  # not used directly
        month = (today.replace(day=1) - datetime.timedelta(days= i*30)).replace(day=1)
        ym = month.strftime("%Y-%m")
        labels.append(month.strftime("%b %Y"))
        c.execute("SELECT COALESCE(SUM(amount),0) as s FROM income WHERE user_id=? AND strftime('%Y-%m', date)=?", (user_id, ym))
        inc_data.append(c.fetchone()['s'])
        c.execute("SELECT COALESCE(SUM(amount),0) as s FROM expense WHERE user_id=? AND strftime('%Y-%m', date)=?", (user_id, ym))
        exp_data.append(c.fetchone()['s'])
    conn.close()
    return total_income, total_expense, labels, inc_data, exp_data

@app.route('/dashboard')
@login_required
def dashboard():
    uid = session['user_id']
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM income WHERE user_id=? ORDER BY date DESC", (uid,))
    incomes = c.fetchall()
    c.execute("SELECT * FROM expense WHERE user_id=? ORDER BY date DESC", (uid,))
    expenses = c.fetchall()
    conn.close()
    total_income, total_expense, labels, inc_data, exp_data = totals_and_monthly(uid)
    savings = total_income - total_expense
    return render_template('dashboard.html',
                           incomes=incomes, expenses=expenses,
                           total_income=total_income, total_expense=total_expense, savings=savings,
                           labels=json.dumps(labels), income_points=json.dumps(inc_data), expense_points=json.dumps(exp_data),
                           pie_income=total_income, pie_expense=total_expense)

# Add income/expense
@app.route('/add_income', methods=['GET','POST'])
@login_required
def add_income():
    if request.method=='POST':
        amount = float(request.form['amount'])
        category = request.form['category']
        date = request.form.get('date') or datetime.date.today().isoformat()
        note = request.form.get('note','')
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO income (user_id, amount, category, date, note) VALUES (?,?,?,?,?)",
                  (session['user_id'], amount, category, date, note))
        conn.commit(); conn.close()
        return redirect(url_for('dashboard'))
    return render_template('add_income.html')

@app.route('/edit_income/<int:id>', methods=['GET','POST'])
@login_required
def edit_income(id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM income WHERE id=? AND user_id=?", (id, session['user_id']))
    row = c.fetchone()
    if not row:
        conn.close(); flash('Not found','danger'); return redirect(url_for('dashboard'))
    if request.method=='POST':
        amount = float(request.form['amount']); category = request.form['category']; date = request.form['date']; note=request.form.get('note','')
        c.execute("UPDATE income SET amount=?, category=?, date=?, note=? WHERE id=?", (amount, category, date, note, id))
        conn.commit(); conn.close(); return redirect(url_for('dashboard'))
    conn.close()
    return render_template('edit_income.html', item=row)

@app.route('/delete_income/<int:id>')
@login_required
def delete_income(id):
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM income WHERE id=? AND user_id=?", (id, session['user_id']))
    conn.commit(); conn.close()
    return redirect(url_for('dashboard'))

# Expense routes (mirror)
@app.route('/add_expense', methods=['GET','POST'])
@login_required
def add_expense():
    if request.method=='POST':
        amount = float(request.form['amount'])
        category = request.form['category']
        date = request.form.get('date') or datetime.date.today().isoformat()
        note = request.form.get('note','')
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO expense (user_id, amount, category, date, note) VALUES (?,?,?,?,?)",
                  (session['user_id'], amount, category, date, note))
        conn.commit(); conn.close()
        return redirect(url_for('dashboard'))
    return render_template('add_expense.html')

@app.route('/edit_expense/<int:id>', methods=['GET','POST'])
@login_required
def edit_expense(id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM expense WHERE id=? AND user_id=?", (id, session['user_id']))
    row = c.fetchone()
    if not row:
        conn.close(); flash('Not found','danger'); return redirect(url_for('dashboard'))
    if request.method=='POST':
        amount = float(request.form['amount']); category = request.form['category']; date = request.form['date']; note=request.form.get('note','')
        c.execute("UPDATE expense SET amount=?, category=?, date=?, note=? WHERE id=?", (amount, category, date, note, id))
        conn.commit(); conn.close(); return redirect(url_for('dashboard'))
    conn.close()
    return render_template('edit_expense.html', item=row)

@app.route('/delete_expense/<int:id>')
@login_required
def delete_expense(id):
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM expense WHERE id=? AND user_id=?", (id, session['user_id']))
    conn.commit(); conn.close()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
