# user_management.py
import json
import os
from cryptography.fernet import Fernet, InvalidToken
import base64
import hashlib

# PySide6 imports needed for the dialogs
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit, QLabel,
    QDialogButtonBox, QMessageBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QGroupBox, QPushButton
)
from PySide6.QtCore import Signal, Qt # Qt for potential future use, QAbstractItemView constants are used

# IMPORTANT: Securely store or generate this key.
# For production, consider hardware security modules or more robust key management.
# Here, we derive a key from a hardcoded password for simplicity in this example.
# DO NOT use this method for high-security production environments without review.
PASSWORD_FOR_KEY = b"EngageWarp!Drive88_Banana"
SALT = b'\x12\x34\x56\x78\x9a\xbc\xde\xf0\x12\x34\x56\x78\x9a\xbc\xde\xf0'
KEY = base64.urlsafe_b64encode(hashlib.pbkdf2_hmac('sha256', PASSWORD_FOR_KEY, SALT, 100000, dklen=32))
F = Fernet(KEY)

USER_FILE = "users.enc"

def load_users():
    """Loads and decrypts user data."""
    if not os.path.exists(USER_FILE):
        # Create default Admin user if file doesn't exist
        save_users({"Administrator": {"name": "Admin", "surname": "", "password": "password"}}) # Default password
        return {"Administrator": {"name": "Admin", "surname": "", "password": "password"}}

    try:
        with open(USER_FILE, "rb") as f:
            encrypted_data = f.read()
        decrypted_data = F.decrypt(encrypted_data)
        users = json.loads(decrypted_data.decode('utf-8'))
        return users
    except (FileNotFoundError, InvalidToken, json.JSONDecodeError, Exception) as e:
        print(f"Error loading or decrypting user file: {e}. Creating default.")
        # Handle potential corruption or decryption failure by resetting
        default_users = {"Administrator": {"name": "Admin", "surname": "", "password": "password"}}
        save_users(default_users)
        return default_users

def save_users(users):
    """Encrypts and saves user data."""
    try:
        data_bytes = json.dumps(users, indent=4).encode('utf-8')
        encrypted_data = F.encrypt(data_bytes)
        with open(USER_FILE, "wb") as f:
            f.write(encrypted_data)
        return True
    except Exception as e:
        print(f"Error encrypting or saving user file: {e}")
        return False

def add_user(users, username, name, surname, password):
    """Adds a new user."""
    if username in users:
        return False, "Username already exists."
    users[username] = {"name": name, "surname": surname, "password": password}
    # The save_users call is now implicitly handled by the dialog if it calls this,
    # or the calling context needs to ensure save_users is called.
    # For UserManagementDialog, it calls save_users after this.
    return True, "User added successfully." # Return success, message; saving is separate

def delete_user(users, username):
    """Deletes a user."""
    if username == "Administrator":
        return False, "Cannot delete the default Administrator."
    if username not in users:
        return False, "User not found."
    del users[username]
    # Similar to add_user, saving is handled by the caller context (UserManagementDialog)
    return True, "User deleted successfully."

def verify_password(users, username, password):
    """Verifies user password."""
    user_data = users.get(username)
    if user_data and user_data.get("password") == password:
        return True
    return False

# --- Moved Dialog Classes ---

class LoginDialog(QDialog):
    login_successful = Signal(str, bool) # username, is_admin

    def __init__(self, users, current_user=None, parent=None): # Add current_user
        super().__init__(parent)
        self.setWindowTitle("Login")
        self.setModal(True)
        self.users = users

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.user_combo = QComboBox()
        # Check if users is not None and is a dictionary before calling keys()
        if self.users and isinstance(self.users, dict):
            self.user_combo.addItems(self.users.keys())
        else:
            print("Warning: LoginDialog received invalid 'users' object.")
            self.users = {} # Ensure self.users is a dict

        # Select current user if provided, else default
        if current_user and current_user in self.users:
             self.user_combo.setCurrentText(current_user)
        elif "Administrator" in self.users:
            self.user_combo.setCurrentText("Administrator")
        elif self.users: # Select first user if Admin not present
            self.user_combo.setCurrentIndex(0)


        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        form_layout.addRow("Username:", self.user_combo)
        form_layout.addRow("Password:", self.password_input)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: red;") # Keep specific error color

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept_login)
        button_box.rejected.connect(self.reject)

        layout.addLayout(form_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(button_box)

        self.password_input.returnPressed.connect(self.accept_login)
        # Set focus based on whether user is pre-selected
        if self.user_combo.currentText():
             self.password_input.setFocus()
        else:
             self.user_combo.setFocus()


    def accept_login(self):
        username = self.user_combo.currentText()
        password = self.password_input.text()

        if not username: # Handle case where combo is empty
             self.status_label.setText("Please select a user.")
             return

        if verify_password(self.users, username, password): # verify_password is in this module
            self.status_label.setText("")
            is_admin = (username == "Administrator")
            self.login_successful.emit(username, is_admin)
            self.accept()
        else:
            self.status_label.setText("Invalid username or password.")
            self.password_input.selectAll()
            self.password_input.setFocus()

class UserManagementDialog(QDialog):
    users_updated = Signal()

    def __init__(self, users, parent=None):
        super().__init__(parent)
        self.setWindowTitle("User Management")
        self.setMinimumWidth(500)
        self.users = users # This will be a reference to the users dict from the main app

        layout = QVBoxLayout(self)

        # User Table
        self.user_table = QTableWidget()
        self.user_table.setColumnCount(3)
        self.user_table.setHorizontalHeaderLabels(["Username", "Name", "Surname"])
        self.user_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.user_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.user_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection) # Ensure only one selected
        self.user_table.verticalHeader().setVisible(False)
        self.user_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.user_table.setAlternatingRowColors(True) # Enable alt row colors
        self.populate_table()
        layout.addWidget(self.user_table)

        # Add User Group
        add_group = QGroupBox("Add New User")
        add_layout = QFormLayout()
        self.new_username = QLineEdit()
        self.new_name = QLineEdit()
        self.new_surname = QLineEdit()
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.EchoMode.Password)
        add_layout.addRow("Username:", self.new_username)
        add_layout.addRow("Name:", self.new_name)
        add_layout.addRow("Surname:", self.new_surname)
        add_layout.addRow("Password:", self.new_password)
        add_button = QPushButton("Add User")
        add_button.clicked.connect(self.add_new_user)
        add_layout.addWidget(add_button)
        add_group.setLayout(add_layout)
        layout.addWidget(add_group)

        # Delete User Button
        delete_button = QPushButton("Delete Selected User")
        delete_button.clicked.connect(self.delete_selected_user)
        layout.addWidget(delete_button)

        # Status Label
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # Close Button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject) # Use reject for close
        layout.addWidget(button_box)

    def populate_table(self):
        self.user_table.setRowCount(0)
        # Sort users alphabetically for consistent display, Administrator first if exists
        # Ensure users is a dict before processing
        if not isinstance(self.users, dict):
            print("Warning: UserManagementDialog.populate_table received invalid 'users' object.")
            self.users = {} # Or handle error appropriately
            return

        sorted_usernames = sorted(self.users.keys())
        if "Administrator" in sorted_usernames:
            sorted_usernames.remove("Administrator")
            sorted_usernames.insert(0, "Administrator")

        for username in sorted_usernames:
            data = self.users[username]
            row_position = self.user_table.rowCount()
            self.user_table.insertRow(row_position)
            self.user_table.setItem(row_position, 0, QTableWidgetItem(username))
            self.user_table.setItem(row_position, 1, QTableWidgetItem(data.get("name", "")))
            self.user_table.setItem(row_position, 2, QTableWidgetItem(data.get("surname", "")))

    def add_new_user(self):
        username = self.new_username.text().strip()
        name = self.new_name.text().strip()
        surname = self.new_surname.text().strip()
        password = self.new_password.text()

        if not username or not password:
            self.status_label.setText("Username and Password cannot be empty.")
            self.status_label.setStyleSheet("color: red;")
            return

        # Call add_user (which modifies self.users in-memory)
        success_add, message_add = add_user(self.users, username, name, surname, password)
        if success_add:
            # Then save the modified self.users to disk
            if save_users(self.users):
                self.status_label.setText(message_add) # Should be "User added successfully."
                self.status_label.setStyleSheet("color: green;")
                self.populate_table()
                self.users_updated.emit() # Signal main app to refresh its user list if needed
                # Clear input fields
                self.new_username.clear()
                self.new_name.clear()
                self.new_surname.clear()
                self.new_password.clear()
            else:
                # save_users failed, potentially roll back the in-memory change or inform user
                self.status_label.setText("Failed to save user data to file.")
                self.status_label.setStyleSheet("color: red;")
                # Consider removing the user from self.users if persistence is critical before success
                if username in self.users: del self.users[username] # Basic rollback
        else:
            self.status_label.setText(message_add) # e.g., "Username already exists."
            self.status_label.setStyleSheet("color: red;")


    def delete_selected_user(self):
        selected_rows = self.user_table.selectionModel().selectedRows()
        if not selected_rows:
            self.status_label.setText("Please select a user to delete.")
            self.status_label.setStyleSheet("color: red;")
            return

        selected_row_index = selected_rows[0].row()
        username_item = self.user_table.item(selected_row_index, 0)
        if not username_item: return

        username_to_delete = username_item.text()

        if username_to_delete == "Administrator":
            QMessageBox.warning(self, "Deletion Denied", "The 'Administrator' user cannot be deleted.")
            return

        reply = QMessageBox.question(self, "Confirm Deletion",
                                     f"Are you sure you want to delete user '{username_to_delete}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            # Store a backup in case save fails, to revert self.users
            original_user_data = self.users.get(username_to_delete)

            success_delete, message_delete = delete_user(self.users, username_to_delete)
            if success_delete:
                if save_users(self.users):
                    self.status_label.setText(message_delete)
                    self.status_label.setStyleSheet("color: green;")
                    self.populate_table()
                    self.users_updated.emit() # Signal main app
                else:
                    self.status_label.setText("Failed to save changes to user data file.")
                    self.status_label.setStyleSheet("color: red;")
                    # Rollback in-memory deletion
                    if original_user_data: self.users[username_to_delete] = original_user_data
            else:
                self.status_label.setText(message_delete)
                self.status_label.setStyleSheet("color: red;")