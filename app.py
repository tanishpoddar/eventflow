import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
import bcrypt
from functools import wraps
from typing import List
import datetime
from flask_migrate import Migrate

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+mysqlconnector://root:Tanishpoddar.18@127.0.0.1/eventhub'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Initialize Flask-Migrate
migrate = Migrate(app, db)

# Add context processor for current year
@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now()}

# --- Database Models ---
class User(db.Model):
    __tablename__ = 'user'
    user_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    user_type = db.Column(db.Enum('organizer', 'attendee', 'administrator'), nullable=False)
    orders = db.relationship('Order', backref='user', lazy=True)

class Venue(db.Model):
    __tablename__ = 'venue'
    venue_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    address = db.Column(db.Text)
    capacity = db.Column(db.Integer)
    city = db.Column(db.String(255))
    state = db.Column(db.String(255))
    zip_code = db.Column(db.String(255))
    events = db.relationship('Event', backref='venue', lazy=True)

class Event(db.Model):
    __tablename__ = 'event'
    event_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=True)  # Keep the old time field for now
    location_id = db.Column(db.Integer, db.ForeignKey('venue.venue_id'), nullable=False)
    speakers = db.relationship('Speaker', backref='event', lazy=True)
    tickets = db.relationship('Ticket', backref='event', lazy=True)
    
    # Properties to handle time information
    _start_time = None
    _end_time = None
    
    @property
    def start_time(self):
        if self._start_time is not None:
            return self._start_time
        elif self.time is not None:
            return self.time
        return None
    
    @start_time.setter
    def start_time(self, value):
        if isinstance(value, str):
            self._start_time = datetime.datetime.strptime(value, '%H:%M').time()
        else:
            self._start_time = value
    
    @property
    def end_time(self):
        if self._end_time is not None:
            return self._end_time
        elif self.time is not None:
            # If we only have the old time field, use it as both start and end
            return self.time
        return None
    
    @end_time.setter
    def end_time(self, value):
        if isinstance(value, str):
            self._end_time = datetime.datetime.strptime(value, '%H:%M').time()
        else:
            self._end_time = value

class Order(db.Model):
    __tablename__ = 'order'
    order_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.payment_id'))
    tickets = db.relationship('Ticket', backref='order', lazy=True)
    payment = db.relationship('Payment', backref=db.backref('order', uselist=False), foreign_keys=[payment_id])

class Payment(db.Model):
    __tablename__ = 'payment'
    payment_id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.order_id'), nullable=False, unique=True)
    payment_method = db.Column(db.Enum('credit card', 'paypal', 'other'), nullable=False)
    transaction_id = db.Column(db.String(255))

class Ticket(db.Model):
    __tablename__ = 'ticket'
    ticket_id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.event_id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('order.order_id'), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    seat_number = db.Column(db.Integer)

class Speaker(db.Model):
    __tablename__ = 'speaker'
    speaker_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    bio = db.Column(db.Text)
    event_id = db.Column(db.Integer, db.ForeignKey('event.event_id'), nullable=False)

class TicketType(db.Model):
    __tablename__ = 'tickettype'
    ticket_type_id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.event_id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    event = db.relationship('Event', backref=db.backref('ticket_types', lazy=True))

# --- Helper Functions ---
def hash_password(password):
    """Hashes a password using bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def check_password(hashed_password, user_password):
    """Checks if the provided password matches the hashed password."""
    return bcrypt.checkpw(user_password.encode('utf-8'), hashed_password)

# --- Decorators ---
def login_required(role="attendee"):
    """Decorator to require login and specific role."""
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))
            user = User.query.get(session['user_id'])
            if not user:
                flash('User not found.', 'danger')
                return redirect(url_for('login'))
            
            # Administrator has access to everything
            if user.user_type == 'administrator':
                return f(*args, **kwargs)
                
            # For non-administrators, check role
            if user.user_type != role:
                if user.user_type == 'organizer' and role == 'attendee':
                    pass  # Allow organizer to see attendee views
                else:
                    flash('You do not have permission to access this page.', 'danger')
                    return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return wrapper

def organizer_required(f):
     """Simplified decorator for organizer role."""
     return login_required(role="organizer")(f)


# --- Routes ---
@app.route('/')
def index():
    """Home page displaying upcoming events."""
    events = Event.query.order_by(Event.date.asc()).limit(6).all() # Show upcoming events
    return render_template('index.html', events=events)

@app.route('/events')
def list_events():
    """Page displaying all events."""
    events = Event.query.order_by(Event.date.asc()).all()
    return render_template('events.html', events=events)

@app.route('/events/<int:event_id>')
def event_details(event_id):
    """Page displaying details for a specific event."""
    event = Event.query.get_or_404(event_id)
    ticket_types = TicketType.query.filter_by(event_id=event_id).all()
    
    # Set time information from form data if available
    if request.args.get('start_time'):
        event.start_time = request.args.get('start_time')
    if request.args.get('end_time'):
        event.end_time = request.args.get('end_time')
    
    return render_template('event_details.html', event=event, ticket_types=ticket_types)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    if 'user_id' in session:
        return redirect(url_for('index')) # Already logged in

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and check_password(user.password.encode('utf-8'), password):
            session['user_id'] = user.user_id
            session['user_name'] = user.name
            session['user_role'] = user.user_type
            flash('Login successful!', 'success')
            if user.user_type == 'organizer':
                 return redirect(url_for('dashboard'))
            else:
                 return redirect(url_for('index'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """Handles user registration."""
    if 'user_id' in session:
        return redirect(url_for('index')) # Already logged in

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        user_type = request.form['user_type']

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('signup.html')

        hashed_pw = hash_password(password)

        new_user = User(name=name, email=email, password=hashed_pw, user_type=user_type)

        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('login'))
        except IntegrityError:
            db.session.rollback()
            flash('Email address already exists.', 'danger')
        except Exception as e:
             db.session.rollback()
             flash(f'An error occurred: {e}', 'danger')


    return render_template('signup.html')

@app.route('/logout')
def logout():
    """Logs the user out."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# --- Organizer Routes (Require 'organizer' role) ---
@app.route('/dashboard')
@organizer_required
def dashboard():
    """Organizer dashboard."""
    # Fetch data relevant to the organizer (e.g., their events)
    # For now, just show all events as an example
    events = Event.query.order_by(Event.date.asc()).all()
    venues = Venue.query.all()
    speakers = Speaker.query.all()
    tickets = Ticket.query.all() # Be cautious with large datasets
    orders = Order.query.all()   # Be cautious with large datasets

    return render_template('dashboard.html',
                           events=events,
                           venues=venues,
                           speakers=speakers,
                           tickets=tickets,
                           orders=orders)


# --- CRUD Operations for Events (Organizer Only) ---

@app.route('/events/create', methods=['GET', 'POST'])
@organizer_required
def create_event():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        date = datetime.datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        location_id = request.form.get('location_id')
        speaker_ids = request.form.getlist('speakers')

        # Create event with the old time field for backward compatibility
        event = Event(
            name=name,
            description=description,
            date=date,
            time=datetime.datetime.strptime(start_time, '%H:%M').time() if start_time else None,
            location_id=location_id
        )

        # Set the new time properties
        event.start_time = start_time
        event.end_time = end_time

        # Add selected speakers
        for speaker_id in speaker_ids:
            speaker = Speaker.query.get(speaker_id)
            if speaker:
                event.speakers.append(speaker)

        try:
            db.session.add(event)
            db.session.commit()
            flash('Event created successfully!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            flash('Error creating event. Please try again.', 'error')
            app.logger.error(f"Error creating event: {str(e)}")

    venues = Venue.query.all()
    speakers = Speaker.query.all()
    return render_template('event_form.html', form_title='Create Event', form_action=url_for('create_event'), venues=venues, all_speakers=speakers)


@app.route('/events/<int:event_id>/edit', methods=['GET', 'POST'])
@organizer_required
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    
    if request.method == 'POST':
        event.name = request.form.get('name')
        event.description = request.form.get('description')
        event.date = datetime.datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        
        # Update the old time field
        start_time = request.form.get('start_time')
        if start_time:
            event.time = datetime.datetime.strptime(start_time, '%H:%M').time()
        
        # Update the new time properties
        event.start_time = start_time
        event.end_time = request.form.get('end_time')
        
        event.location_id = request.form.get('location_id')
        
        # Update speakers
        event.speakers = []
        for speaker_id in request.form.getlist('speakers'):
            speaker = Speaker.query.get(speaker_id)
            if speaker:
                event.speakers.append(speaker)

        try:
            db.session.commit()
            flash('Event updated successfully!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            flash('Error updating event. Please try again.', 'error')
            app.logger.error(f"Error updating event: {str(e)}")

    venues = Venue.query.all()
    speakers = Speaker.query.all()
    return render_template('event_form.html', form_title='Edit Event', form_action=url_for('edit_event', event_id=event_id), event=event, venues=venues, all_speakers=speakers)


@app.route('/events/<int:event_id>/delete', methods=['POST'])
@organizer_required
def delete_event(event_id):
    """Delete an event."""
    event = Event.query.get_or_404(event_id)
    try:
        # Manually delete related Speakers and Tickets if cascade doesn't work as expected
        # Speaker.query.filter_by(event_id=event_id).delete()
        # Ticket.query.filter_by(event_id=event_id).delete()
        db.session.delete(event)
        db.session.commit()
        flash('Event deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting event: {e}', 'danger')
    return redirect(url_for('dashboard'))


# --- CRUD Operations for Venues (Organizer Only) ---

@app.route('/venues/create', methods=['GET', 'POST'])
@organizer_required
def create_venue():
     if request.method == 'POST':
        name = request.form['name']
        address = request.form.get('address')
        capacity = request.form.get('capacity', type=int)
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip_code')
        new_venue = Venue(name=name, address=address, capacity=capacity, city=city, state=state, zip_code=zip_code)
        try:
             db.session.add(new_venue)
             db.session.commit()
             flash('Venue created successfully!', 'success')
             return redirect(url_for('dashboard'))
        except Exception as e:
             db.session.rollback()
             flash(f'Error creating venue: {e}', 'danger')
     return render_template('venue_form.html', form_action=url_for('create_venue'), form_title="Create New Venue")


@app.route('/venues/<int:venue_id>/edit', methods=['GET', 'POST'])
@organizer_required
def edit_venue(venue_id):
     venue = Venue.query.get_or_404(venue_id)
     if request.method == 'POST':
         venue.name = request.form['name']
         venue.address = request.form.get('address')
         venue.capacity = request.form.get('capacity', type=int)
         venue.city = request.form.get('city')
         venue.state = request.form.get('state')
         venue.zip_code = request.form.get('zip_code')
         try:
             db.session.commit()
             flash('Venue updated successfully!', 'success')
             return redirect(url_for('dashboard'))
         except Exception as e:
             db.session.rollback()
             flash(f'Error updating venue: {e}', 'danger')
     return render_template('venue_form.html', venue=venue, form_action=url_for('edit_venue', venue_id=venue_id), form_title="Edit Venue")


@app.route('/venues/<int:venue_id>/delete', methods=['POST'])
@organizer_required
def delete_venue(venue_id):
     venue = Venue.query.get_or_404(venue_id)
     if venue.events: # Check if venue is linked to events
          flash('Cannot delete venue. It is linked to existing events.', 'danger')
          return redirect(url_for('dashboard'))
     try:
         db.session.delete(venue)
         db.session.commit()
         flash('Venue deleted successfully!', 'success')
     except Exception as e:
         db.session.rollback()
         flash(f'Error deleting venue: {e}', 'danger')
     return redirect(url_for('dashboard'))


# --- CRUD Operations for Speakers (Organizer Only) ---

@app.route('/speakers/create', methods=['GET', 'POST'])
@organizer_required
def create_speaker():
     events = Event.query.order_by(Event.name).all()
     if request.method == 'POST':
         name = request.form['name']
         bio = request.form.get('bio')
         event_id = request.form['event_id']
         new_speaker = Speaker(name=name, bio=bio, event_id=event_id)
         try:
             db.session.add(new_speaker)
             db.session.commit()
             flash('Speaker created successfully!', 'success')
             return redirect(url_for('dashboard'))
         except Exception as e:
             db.session.rollback()
             flash(f'Error creating speaker: {e}', 'danger')
     return render_template('speaker_form.html', events=events, form_action=url_for('create_speaker'), form_title="Add New Speaker")


@app.route('/speakers/<int:speaker_id>/edit', methods=['GET', 'POST'])
@organizer_required
def edit_speaker(speaker_id):
     speaker = Speaker.query.get_or_404(speaker_id)
     events = Event.query.order_by(Event.name).all()
     if request.method == 'POST':
         speaker.name = request.form['name']
         speaker.bio = request.form.get('bio')
         speaker.event_id = request.form['event_id']
         try:
             db.session.commit()
             flash('Speaker updated successfully!', 'success')
             return redirect(url_for('dashboard'))
         except Exception as e:
             db.session.rollback()
             flash(f'Error updating speaker: {e}', 'danger')
     return render_template('speaker_form.html', speaker=speaker, events=events, form_action=url_for('edit_speaker', speaker_id=speaker_id), form_title="Edit Speaker")


@app.route('/speakers/<int:speaker_id>/delete', methods=['POST'])
@organizer_required
def delete_speaker(speaker_id):
     speaker = Speaker.query.get_or_404(speaker_id)
     try:
         db.session.delete(speaker)
         db.session.commit()
         flash('Speaker deleted successfully!', 'success')
     except Exception as e:
         db.session.rollback()
         flash(f'Error deleting speaker: {e}', 'danger')
     return redirect(url_for('dashboard'))


# --- CRUD Operations for Tickets (Conceptual - Booking is attendee, managing is organizer) ---
# Note: Full ticket CRUD might be complex. Organizer might manage ticket *types* per event.

@app.route('/events/<int:event_id>/tickets/manage', methods=['GET', 'POST'])
@organizer_required
def manage_event_tickets(event_id):
    """Manage ticket types for an event."""
    event = Event.query.get_or_404(event_id)
    
    if request.method == 'POST':
        ticket_type = request.form['type']
        price = float(request.form['price'])
        quantity = int(request.form['quantity'])

        # Calculate total tickets including existing ones
        existing_tickets = TicketType.query.filter_by(event_id=event_id).all()
        total_tickets = sum(t.quantity for t in existing_tickets) + quantity

        # Check if total tickets exceed venue capacity
        if total_tickets > event.venue.capacity:
            flash(f'Total tickets ({total_tickets}) cannot exceed venue capacity ({event.venue.capacity}).', 'danger')
            return redirect(url_for('manage_event_tickets', event_id=event_id))

        new_ticket_type = TicketType(
            event_id=event_id,
            type=ticket_type,
            price=price,
            quantity=quantity
        )

        try:
            db.session.add(new_ticket_type)
            db.session.commit()
            flash('Ticket type added successfully!', 'success')
            return redirect(url_for('manage_event_tickets', event_id=event_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding ticket type: {str(e)}', 'danger')

    ticket_types = TicketType.query.filter_by(event_id=event_id).all()
    return render_template('manage_tickets.html', event=event, ticket_types=ticket_types)

@app.route('/events/<int:event_id>/tickets')
@login_required(role="organizer")
def view_event_tickets(event_id):
    """View all tickets for an event (organizers and admins only)"""
    event = Event.query.get_or_404(event_id)
    # Get all tickets for this event with user and order information
    tickets = Ticket.query.join(Order).join(User).filter(Ticket.event_id == event_id).all()
    return render_template('event_tickets.html', event=event, tickets=tickets)

@app.route('/tickets/<int:ticket_id>/delete', methods=['POST'])
@login_required(role="organizer")
def delete_ticket(ticket_id):
    """Delete a ticket type."""
    ticket_type = TicketType.query.get_or_404(ticket_id)
    event_id = ticket_type.event_id
    
    try:
        # Delete associated tickets first
        Ticket.query.filter_by(event_id=event_id, type=ticket_type.type).delete()
        db.session.delete(ticket_type)
        db.session.commit()
        flash('Ticket type deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting ticket type: {str(e)}', 'danger')
    
    return redirect(url_for('manage_event_tickets', event_id=event_id))

@app.route('/tickets/<int:ticket_id>/cancel', methods=['POST'])
@login_required(role="attendee")
def cancel_ticket(ticket_id):
    """Cancel a ticket (attendees only)"""
    # Get the ticket and verify ownership
    ticket = Ticket.query.get_or_404(ticket_id)
    order = ticket.order
    
    # Check if the ticket belongs to the current user
    if order.user_id != session['user_id']:
        flash('You do not have permission to cancel this ticket.', 'danger')
        return redirect(url_for('my_tickets'))
    
    try:
        # Start a new transaction
        db.session.begin_nested()
        
        # Increment the ticket type quantity
        ticket_type = TicketType.query.filter_by(
            event_id=ticket.event_id,
            type=ticket.type
        ).first()
        if ticket_type:
            ticket_type.quantity += 1
        
        # Get the order and all its tickets
        order_id = ticket.order_id
        event_id = ticket.event_id
        ticket_type_name = ticket.type
        
        # Delete the specific ticket
        db.session.delete(ticket)
        db.session.flush()  # Flush to ensure the ticket is deleted
        
        # Check if there are any remaining tickets in the order
        remaining_tickets = Ticket.query.filter_by(order_id=order_id).all()
        
        if not remaining_tickets:
            # If no tickets remain, delete the order
            order = Order.query.get(order_id)
            if order:
                db.session.delete(order)
        else:
            # Update the order total price
            order = Order.query.get(order_id)
            if order:
                new_total = sum(float(t.price) for t in remaining_tickets)
                order.total_price = new_total
        
        # Commit the transaction
        db.session.commit()
        flash('Ticket cancelled successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error cancelling ticket: {str(e)}', 'danger')
    
    return redirect(url_for('my_tickets'))

# --- Attendee Actions ---
@app.route('/book_ticket/<int:event_id>', methods=['POST'])
def book_ticket(event_id):
    if 'user_id' not in session or session.get('user_role') != 'attendee':
        flash('Please login as an attendee to book tickets.', 'danger')
        return redirect(url_for('login'))
    
    event = Event.query.get_or_404(event_id)
    ticket_type_name = request.form.get('ticket_type')
    quantity = int(request.form.get('quantity', 1))
    
    # Find the ticket type by name
    ticket_type = TicketType.query.filter_by(
        event_id=event_id,
        type=ticket_type_name
    ).first()
    
    if not ticket_type or quantity < 1 or quantity > ticket_type.quantity:
        flash('Invalid ticket selection or not enough tickets available.', 'danger')
        return redirect(url_for('event_details', event_id=event_id))
    
    try:
        # Create order
        order = Order(
            user_id=session['user_id'],
            date=datetime.datetime.now(),
            total_price=ticket_type.price * quantity
        )
        db.session.add(order)
        db.session.flush()  # Get order_id
        
        # Create tickets
        for _ in range(quantity):
            ticket = Ticket(
                event_id=event_id,
                order_id=order.order_id,
                price=ticket_type.price,
                type=ticket_type.type
            )
            db.session.add(ticket)
        
        # Update available tickets
        ticket_type.quantity -= quantity
        
        db.session.commit()
        flash(f'Successfully booked {quantity} {ticket_type.type} ticket(s)!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while booking tickets.', 'danger')
        app.logger.error(f"Error booking tickets: {str(e)}")
    
    return redirect(url_for('event_details', event_id=event_id))

@app.route('/my-tickets')
@login_required(role="attendee")
def my_tickets():
     """Displays tickets booked by the current attendee."""
     user_id = session['user_id']
     # Fetch orders and associated tickets for the user
     orders = Order.query.filter_by(user_id=user_id).options(db.joinedload(Order.tickets).joinedload(Ticket.event)).order_by(Order.date.desc()).all()
     # tickets = Ticket.query.join(Order).filter(Order.user_id == user_id).options(db.joinedload(Ticket.event)).all() # Alternative query
     return render_template('my_tickets.html', orders=orders)

@app.route('/admin/organizers')
@login_required(role="administrator")
def manage_organizers():
    """Administrator view to manage organizers."""
    organizers = User.query.filter_by(user_type='organizer').all()
    return render_template('manage_organizers.html', organizers=organizers)

@app.route('/admin/organizers/<int:user_id>/delete', methods=['POST'])
@login_required(role="administrator")
def delete_organizer(user_id):
    """Delete an organizer (admin only)."""
    organizer = User.query.get_or_404(user_id)
    if organizer.user_type != 'organizer':
        flash('User is not an organizer.', 'danger')
        return redirect(url_for('manage_organizers'))
    
    try:
        # Delete associated events and tickets
        events = Event.query.filter_by(organizer_id=user_id).all()
        for event in events:
            # Delete associated tickets
            Ticket.query.filter_by(event_id=event.event_id).delete()
            # Delete ticket types
            TicketType.query.filter_by(event_id=event.event_id).delete()
            # Delete speakers
            Speaker.query.filter_by(event_id=event.event_id).delete()
            # Delete the event
            db.session.delete(event)
        
        # Delete the organizer
        db.session.delete(organizer)
        db.session.commit()
        flash('Organizer and all associated data deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting organizer: {str(e)}', 'danger')
    
    return redirect(url_for('manage_organizers'))

# --- Main Execution ---
if __name__ == '__main__':
    with app.app_context():
        # Create database tables if they don't exist
        # In production, consider using Flask-Migrate for database migrations
        db.create_all()
    app.run(debug=True) # Set debug=False in production
