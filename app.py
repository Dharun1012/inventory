# --- PATCH: Fix ReportLab MD5 bug (for Python 3.12+) ---
import hashlib
import reportlab.pdfbase.pdfdoc as pdfdoc

def _md5_fixed(*args, **kwargs):
    """Fix for usedforsecurity argument in newer Python versions."""
    data = args[0] if args else b""
    return hashlib.md5(data)

pdfdoc.md5 = _md5_fixed
# -------------------------------------------------------
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Product, Location, ProductMovement
from sqlalchemy import func
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart



app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email configuration (update with your email)
ADMIN_EMAIL = "thortharun95@gmail.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "thortharun95@gmail.com"
SENDER_PASSWORD = "yxlbkiyfctxrjccp"

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def send_low_stock_email(product_name, current_stock, min_stock):
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = ADMIN_EMAIL
        msg['Subject'] = f'Low Stock Alert: {product_name}'
        
        body = f"""
        <html>
        <body>
            <h2>Low Stock Alert!</h2>
            <p><strong>Product:</strong> {product_name}</p>
            <p><strong>Current Stock:</strong> {current_stock}</p>
            <p><strong>Minimum Stock:</strong> {min_stock}</p>
            <p>Please reorder this product immediately.</p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Email sent for {product_name}")
    except Exception as e:
        print(f"Failed to send email: {e}")

def get_product_total_stock(product_id):
    """Calculate total stock across all locations for a product"""
    incoming = db.session.query(func.sum(ProductMovement.qty)).filter(
        ProductMovement.product_id == product_id,
        ProductMovement.to_location.isnot(None)
    ).scalar() or 0
    
    outgoing = db.session.query(func.sum(ProductMovement.qty)).filter(
        ProductMovement.product_id == product_id,
        ProductMovement.from_location.isnot(None),
        ProductMovement.to_location.is_(None)  # Only count actual outgoing (sales), not transfers
    ).scalar() or 0
    
    return incoming - outgoing

def get_low_stock_products():
    low_stock = []
    products = Product.query.all()
    
    for product in products:
        current_stock = get_product_total_stock(product.product_id)
        
        if current_stock <= product.min_stock:
            low_stock.append({
                'product': product.name,
                'product_id': product.product_id,
                'stock': current_stock,
                'min': product.min_stock
            })
    
    return low_stock

def init_db():
    with app.app_context():
        db.create_all()
        
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                password=generate_password_hash('admin123'),
                email=ADMIN_EMAIL
            )
            db.session.add(admin)
        
        if Product.query.count() == 0:
            products = [
                Product(product_id='PROD001', name='Face Wash', description='Gentle cleansing face wash', min_stock=10),
                Product(product_id='PROD002', name='Serum', description='Anti-aging serum', min_stock=10),
                Product(product_id='PROD003', name='Sunscreen', description='SPF 50+ sunscreen', min_stock=10)
            ]
            for p in products:
                db.session.add(p)
        
        if Location.query.count() == 0:
            locations = [
                Location(location_id='WH001', name='Main Warehouse', description='Primary storage facility'),
                Location(location_id='WH002', name='Store A', description='Retail outlet A'),
                Location(location_id='WH003', name='Warehouse B', description='Secondary warehouse'),
                Location(location_id='WH004', name='Distribution Center', description='Central distribution hub')
            ]
            for l in locations:
                db.session.add(l)
        
        db.session.commit()
        
        if ProductMovement.query.count() == 0:
            movements = [
                # Initial stock to Main Warehouse
                ProductMovement(product_id='PROD001', to_location='WH001', qty=50),
                ProductMovement(product_id='PROD002', to_location='WH001', qty=30),
                ProductMovement(product_id='PROD003', to_location='WH001', qty=40),
                
                # Transfer from Main Warehouse to Store A
                ProductMovement(product_id='PROD001', from_location='WH001', to_location='WH002', qty=15),
                ProductMovement(product_id='PROD002', from_location='WH001', to_location='WH002', qty=10),
                ProductMovement(product_id='PROD003', from_location='WH001', to_location='WH002', qty=12),
            ]
            for m in movements:
                db.session.add(m)
            db.session.commit()

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/api/low-stock-count')
@login_required
def low_stock_count():
    low_stock = get_low_stock_products()
    return jsonify({'count': len(low_stock)})

@app.route('/dashboard')
@login_required
def dashboard():
    products = Product.query.all()
    locations = Location.query.count()
    movements = ProductMovement.query.count()
    
    low_stock = get_low_stock_products()
    
    # Total stock per product
    total_stock = []
    for product in products:
        total = get_product_total_stock(product.product_id)
        total_stock.append({'product': product.name, 'total': total})
    
    return render_template('dashboard.html', 
                         total_products=len(products),
                         total_locations=locations,
                         total_movements=movements,
                         low_stock=low_stock,
                         total_stock=total_stock)

@app.route('/products', methods=['GET', 'POST'])
@login_required
def products():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            last_product = Product.query.order_by(Product.product_id.desc()).first()
            new_id = f'PROD{(int(last_product.product_id[4:]) + 1):03d}' if last_product else 'PROD001'
            
            qty = int(request.form.get('qty', 0))
            product = Product(
                product_id=new_id,
                name=request.form.get('name'),
                description=request.form.get('description'),
                min_stock=5
            )
            db.session.add(product)
            db.session.commit()

            # Add initial stock as a movement to main warehouse (WH001)
            if qty > 0:
                movement = ProductMovement(product_id=new_id, to_location='WH001', qty=qty)
                db.session.add(movement)
                db.session.commit()

            flash(f'Product {new_id} added successfully with {qty} units!', 'success')

        elif action == 'edit':
            product_id = request.form.get('product_id')
            product = Product.query.get(product_id)
            if product:
                product.name = request.form.get('name')
                product.description = request.form.get('description')
                db.session.commit()

                # Adjust stock difference via movement
                new_qty = int(request.form.get('qty', 0))
                current_stock = get_product_total_stock(product_id)
                diff = new_qty - current_stock

                if diff != 0:
                    if diff > 0:
                        move = ProductMovement(product_id=product_id, to_location='WH001', qty=diff)
                    else:
                        move = ProductMovement(product_id=product_id, from_location='WH001', qty=abs(diff))
                    db.session.add(move)
                    db.session.commit()

                flash('Product updated successfully!', 'success')

        elif action == 'delete':
            product = Product.query.get(request.form.get('product_id'))
            if product:
                ProductMovement.query.filter_by(product_id=product.product_id).delete()
                db.session.delete(product)
                db.session.commit()
                flash('Product deleted successfully!', 'success')

        return redirect(url_for('products'))

    products = Product.query.all()
    product_data = []
    for p in products:
        total_qty = get_product_total_stock(p.product_id)
        product_data.append({
            'product_id': p.product_id,
            'name': p.name,
            'description': p.description,
            'total_qty': total_qty
        })

    return render_template('products.html', products=product_data)



@app.route('/locations', methods=['GET', 'POST'])
@login_required
def locations():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            last_location = Location.query.order_by(Location.location_id.desc()).first()
            if last_location:
                num = int(last_location.location_id[2:]) + 1
                new_id = f'WH{num:03d}'
            else:
                new_id = 'WH001'
            
            location = Location(
                location_id=new_id,
                name=request.form.get('name'),
                description=request.form.get('description')
            )
            db.session.add(location)
            db.session.commit()
            flash(f'Location {new_id} added successfully!', 'success')
        
        elif action == 'edit':
            location = Location.query.get(request.form.get('location_id'))
            if location:
                location.name = request.form.get('name')
                location.description = request.form.get('description')
                db.session.commit()
                flash('Location updated successfully!', 'success')
        
        elif action == 'delete':
            location = Location.query.get(request.form.get('location_id'))
            if location:
                db.session.delete(location)
                db.session.commit()
                flash('Location deleted successfully!', 'success')
        
        return redirect(url_for('locations'))
    
    locations = Location.query.all()
    return render_template('locations.html', locations=locations)

@app.route('/movements', methods=['GET', 'POST'])
@login_required
def movements():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            product_id = request.form.get('product_id')
            qty = int(request.form.get('qty'))
            from_loc = request.form.get('from_location') or None
            to_loc = request.form.get('to_location') or None
            
            # Validation: must have at least one location
            if not from_loc and not to_loc:
                flash('Please specify at least one location (From or To)', 'danger')
                return redirect(url_for('movements'))
            
            # If moving FROM a location, check if enough stock exists
            if from_loc:
                incoming = db.session.query(func.sum(ProductMovement.qty)).filter(
                    ProductMovement.product_id == product_id,
                    ProductMovement.to_location == from_loc
                ).scalar() or 0
                
                outgoing = db.session.query(func.sum(ProductMovement.qty)).filter(
                    ProductMovement.product_id == product_id,
                    ProductMovement.from_location == from_loc
                ).scalar() or 0
                
                available = incoming - outgoing
                
                if available < qty:
                    flash(f'Insufficient stock! Only {available} units available at this location.', 'danger')
                    return redirect(url_for('movements'))
            
            movement = ProductMovement(
                product_id=product_id,
                from_location=from_loc,
                to_location=to_loc,
                qty=qty
            )
            db.session.add(movement)
            db.session.commit()
            
            # Check for low stock and send email
            product = Product.query.get(product_id)
            total_stock = get_product_total_stock(product_id)
            
            if total_stock <= product.min_stock:
                send_low_stock_email(product.name, total_stock, product.min_stock)
            
            flash('Movement recorded successfully!', 'success')
        
        elif action == 'delete':
            movement = ProductMovement.query.get(request.form.get('movement_id'))
            if movement:
                db.session.delete(movement)
                db.session.commit()
                flash('Movement deleted successfully!', 'success')
        
        return redirect(url_for('movements'))
    
    movements = ProductMovement.query.order_by(ProductMovement.timestamp.desc()).all()
    products = Product.query.all()
    locations = Location.query.all()
    return render_template('movements.html', movements=movements, products=products, locations=locations)

@app.route('/report')
@login_required
def report():
    report_data = []
    products = Product.query.all()
    locations = Location.query.all()
    
    for location in locations:
        for product in products:
            incoming = db.session.query(func.sum(ProductMovement.qty)).filter(
                ProductMovement.product_id == product.product_id,
                ProductMovement.to_location == location.location_id
            ).scalar() or 0
            
            outgoing = db.session.query(func.sum(ProductMovement.qty)).filter(
                ProductMovement.product_id == product.product_id,
                ProductMovement.from_location == location.location_id
            ).scalar() or 0
            
            balance = incoming - outgoing
            if balance > 0:  # Only show locations with stock
                report_data.append({
                    'product': product.name,
                    'location': location.name,
                    'qty': balance
                })
    
    return render_template('report.html', report_data=report_data)

@app.route('/report/pdf')
@login_required
def report_pdf():
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    p.setFont("Helvetica-Bold", 16)
    p.drawString(1*inch, height - 1*inch, "Inventory Balance Report")
    
    p.setFont("Helvetica-Bold", 10)
    y = height - 1.5*inch
    p.drawString(1*inch, y, "Product")
    p.drawString(3*inch, y, "Location")
    p.drawString(5*inch, y, "Quantity")
    
    p.setFont("Helvetica", 10)
    y -= 0.3*inch
    
    products = Product.query.all()
    locations = Location.query.all()
    
    for location in locations:
        for product in products:
            incoming = db.session.query(func.sum(ProductMovement.qty)).filter(
                ProductMovement.product_id == product.product_id,
                ProductMovement.to_location == location.location_id
            ).scalar() or 0
            
            outgoing = db.session.query(func.sum(ProductMovement.qty)).filter(
                ProductMovement.product_id == product.product_id,
                ProductMovement.from_location == location.location_id
            ).scalar() or 0
            
            balance = incoming - outgoing
            if balance > 0:
                p.drawString(1*inch, y, product.name)
                p.drawString(3*inch, y, location.name)
                p.drawString(5*inch, y, str(balance))
                y -= 0.25*inch
                
                if y < 1*inch:
                    p.showPage()
                    p.setFont("Helvetica", 10)
                    y = height - 1*inch
    
    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='inventory_report.pdf', mimetype='application/pdf')

if __name__ == '__main__':
    init_db()
    app.run(debug=True)




@app.route('/api/product-locations/<product_id>')
@login_required
def product_locations(product_id):
    """Get stock breakdown by location for a specific product"""
    locations = Location.query.all()
    location_data = []
    
    for location in locations:
        incoming = db.session.query(func.sum(ProductMovement.qty)).filter(
            ProductMovement.product_id == product_id,
            ProductMovement.to_location == location.location_id
        ).scalar() or 0
        
        outgoing = db.session.query(func.sum(ProductMovement.qty)).filter(
            ProductMovement.product_id == product_id,
            ProductMovement.from_location == location.location_id
        ).scalar() or 0
        
        balance = incoming - outgoing
        if balance > 0:
            location_data.append({
                'location': location.name,
                'qty': balance
            })
    
    return jsonify({'locations': location_data})