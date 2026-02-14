"""
Email utility module for sending password reset emails.

Provides functions for sending emails via SMTP with proper error handling.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional


def send_password_reset_email(to_email: str, reset_token: str, reset_url_base: str) -> bool:
    """
    Send password reset email to user.

    Args:
        to_email: Recipient email address.
        reset_token: Password reset token.
        reset_url_base: Base URL for password reset (e.g., https://yourapp.com/reset-password).

    Returns:
        True if email sent successfully, False otherwise.
    """
    # Get SMTP configuration from environment variables
    smtp_host = os.getenv("SMTP_HOST", "localhost")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from_email = os.getenv("SMTP_FROM_EMAIL", "noreply@pslpredictor.com")
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "PSL Soccer Predictor")
    
    # For development/testing, allow disabling email sending
    if os.getenv("DISABLE_EMAIL", "false").lower() == "true":
        print(f"[email] Email sending disabled. Reset token: {reset_token}")
        print(f"[email] Reset URL: {reset_url_base}?token={reset_token}")
        return True
    
    try:
        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = "Password Reset Request - PSL Soccer Predictor"
        message["From"] = f"{smtp_from_name} <{smtp_from_email}>"
        message["To"] = to_email
        
        # Create reset URL
        reset_url = f"{reset_url_base}?token={reset_token}"
        
        # Plain text version
        text_body = f"""
Hello,

You have requested to reset your password for PSL Soccer Predictor.

Please click the link below to reset your password:
{reset_url}

This link will expire in 1 hour.

If you did not request a password reset, please ignore this email.

Best regards,
PSL Soccer Predictor Team
"""
        
        # HTML version
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .button {{ 
            display: inline-block; 
            padding: 12px 24px; 
            background-color: #007bff; 
            color: white; 
            text-decoration: none; 
            border-radius: 4px; 
            margin: 20px 0; 
        }}
        .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>Password Reset Request</h2>
        <p>Hello,</p>
        <p>You have requested to reset your password for PSL Soccer Predictor.</p>
        <p>Please click the button below to reset your password:</p>
        <a href="{reset_url}" class="button">Reset Password</a>
        <p>Or copy and paste this link into your browser:</p>
        <p><a href="{reset_url}">{reset_url}</a></p>
        <p>This link will expire in 1 hour.</p>
        <p>If you did not request a password reset, please ignore this email.</p>
        <div class="footer">
            <p>Best regards,<br>PSL Soccer Predictor Team</p>
        </div>
    </div>
</body>
</html>
"""
        
        # Attach both versions
        part_text = MIMEText(text_body, "plain")
        part_html = MIMEText(html_body, "html")
        message.attach(part_text)
        message.attach(part_html)
        
        # Send email
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(message)
        
        print(f"[email] Password reset email sent to {to_email}")
        return True
        
    except Exception as e:
        print(f"[email] Failed to send password reset email: {e}")
        return False


def send_password_reset_confirmation_email(to_email: str) -> bool:
    """
    Send confirmation email after successful password reset.

    Args:
        to_email: Recipient email address.

    Returns:
        True if email sent successfully, False otherwise.
    """
    # Get SMTP configuration from environment variables
    smtp_host = os.getenv("SMTP_HOST", "localhost")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from_email = os.getenv("SMTP_FROM_EMAIL", "noreply@pslpredictor.com")
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "PSL Soccer Predictor")
    
    # For development/testing, allow disabling email sending
    if os.getenv("DISABLE_EMAIL", "false").lower() == "true":
        print(f"[email] Email sending disabled. Password reset confirmation for {to_email}")
        return True
    
    try:
        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = "Password Reset Successful - PSL Soccer Predictor"
        message["From"] = f"{smtp_from_name} <{smtp_from_email}>"
        message["To"] = to_email
        
        # Plain text version
        text_body = f"""
Hello,

Your password has been successfully reset for PSL Soccer Predictor.

If you did not perform this action, please contact our support team immediately.

Best regards,
PSL Soccer Predictor Team
"""
        
        # HTML version
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .alert {{ 
            padding: 12px; 
            background-color: #d4edda; 
            border: 1px solid #c3e6cb; 
            border-radius: 4px; 
            color: #155724; 
            margin: 20px 0; 
        }}
        .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>Password Reset Successful</h2>
        <div class="alert">
            Your password has been successfully reset.
        </div>
        <p>You can now log in to PSL Soccer Predictor with your new password.</p>
        <p>If you did not perform this action, please contact our support team immediately.</p>
        <div class="footer">
            <p>Best regards,<br>PSL Soccer Predictor Team</p>
        </div>
    </div>
</body>
</html>
"""
        
        # Attach both versions
        part_text = MIMEText(text_body, "plain")
        part_html = MIMEText(html_body, "html")
        message.attach(part_text)
        message.attach(part_html)
        
        # Send email
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(message)
        
        print(f"[email] Password reset confirmation email sent to {to_email}")
        return True
        
    except Exception as e:
        print(f"[email] Failed to send password reset confirmation email: {e}")
        return False
