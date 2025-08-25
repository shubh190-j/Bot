
import asyncio
import logging
import os
import re
from io import StringIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- New imports for Flask ---
from flask import Flask
from threading import Thread

# --- Flask App Setup ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!", 200

def run_flask():
    app.run(host='0.0.0.0', port=10000)

# Start the Flask server in a separate thread
flask_thread = Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()


# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

class VCFConverter:
    def __init__(self):
        self.user_data = {}
    
    def parse_contacts_from_text(self, text):
        """Parse contacts from text file - handles various formats"""
        contacts = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Try to extract phone numbers
            phone_pattern = r'[\+]?[1-9]?[0-9]{7,15}'
            phones = re.findall(phone_pattern, line)
            
            if phones:
                # Try to extract name (everything before the first phone number)
                name_match = re.split(phone_pattern, line)[0].strip()
                name = name_match if name_match else None
                
                for phone in phones:
                    contacts.append({
                        'name': name,
                        'phone': phone.strip()
                    })
            else:
                # If no phone pattern found, treat the whole line as a phone
                if line.replace('+', '').replace('-', '').replace(' ', '').isdigit():
                    contacts.append({
                        'name': None,
                        'phone': line
                    })
        
        return contacts
    
    def create_vcf_content(self, contacts, base_name=None):
        """Create VCF content from contacts list"""
        vcf_content = ""
        
        for i, contact in enumerate(contacts, 1):
            name = contact['name']
            if not name and base_name:
                name = f"{base_name} {i}"
            elif not name:
                name = f"Contact {i}"
            
            vcf_content += f"BEGIN:VCARD\n"
            vcf_content += f"VERSION:3.0\n"
            vcf_content += f"FN:{name}\n"
            vcf_content += f"TEL:{contact['phone']}\n"
            vcf_content += f"END:VCARD\n\n"
        
        return vcf_content
    
    def split_contacts(self, contacts, chunk_size):
        """Split contacts into chunks of specified size"""
        chunks = []
        for i in range(0, len(contacts), chunk_size):
            chunks.append(contacts[i:i + chunk_size])
        return chunks

# Initialize converter
converter = VCFConverter()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    welcome_message = """
🤖 *VCF Converter Bot*

Welcome! I can help you convert text files to VCF format.

*Available Commands:*
/start - Show this message
/restart - Restart the bot if it's slow
/help - Show help information

*How to use:*
1. Send me a text file with contacts
2. If contacts don't have names, I'll ask for a base name
3. Choose split options or keep all in one file

Just send me your contact file to get started! 📱
    """
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart command to fix bot issues"""
    await update.message.reply_text("🔄 Bot restarted successfully! Ready to process your files.")
    # Clear user data for this user
    user_id = update.effective_user.id
    if user_id in converter.user_data:
        del converter.user_data[user_id]

async def lord(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lord command to forcefully restart the bot"""
    await update.message.reply_text("👑 LORD COMMAND ACTIVATED!\n🔄 Bot is restarting with full power...")
    # Clear all user data
    converter.user_data.clear()
    await update.message.reply_text("✅ Bot has been completely refreshed and is ready to serve!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler"""
    help_text = """
🆘 *Help - VCF Converter Bot*

*Supported file formats:*
- Text files (.txt)
- Any text content with phone numbers

*Features:*
- Auto-detect phone numbers
- Split into multiple VCF files (35, 40, 50, 75, 100, 150, 200 contacts)
- Keep all contacts in one file
- Auto-name contacts if no names provided
- Custom VCF file names with contact ranges

*Commands:*
/start - Start the bot
/restart - Fix slow/stuck bot
/lord - Force restart with full refresh
/help - Show this help

*Usage Example:*
1. Send a .txt file with contacts like:
   ```
   John Doe +1234567890
   Jane Smith +0987654321
   +1122334455
   ```
2. Choose split option or single file
3. Enter custom filename (e.g., 'zeno')
4. Get files named like: zeno_1-50.vcf, zeno_51-100.vcf
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads"""
    user_id = update.effective_user.id
    document = update.message.document
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please send a .txt file containing contacts.")
        return
    
    try:
        # Download the file
        file = await context.bot.get_file(document.file_id)
        file_content = await file.download_as_bytearray()
        text_content = file_content.decode('utf-8')
        
        # Parse contacts
        contacts = converter.parse_contacts_from_text(text_content)
        
        if not contacts:
            await update.message.reply_text("❌ No valid contacts found in the file. Please check the format.")
            return
        
        # Store contacts for this user
        converter.user_data[user_id] = {'contacts': contacts}
        
        # Check if contacts have names
        contacts_without_names = [c for c in contacts if not c['name']]
        
        if contacts_without_names:
            await update.message.reply_text(
                f"📋 Found {len(contacts)} contacts, but {len(contacts_without_names)} don't have names.\n\n"
                "Please send a base name for the unnamed contacts (e.g., 'Shubh'):"
            )
            converter.user_data[user_id]['waiting_for_name'] = True
        else:
            await show_split_options(update, len(contacts))
            
    except Exception as e:
        logger.error(f"Error processing document: {e}")
        await update.message.reply_text("❌ Error processing file. Please try again.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    user_id = update.effective_user.id
    
    if user_id not in converter.user_data:
        await update.message.reply_text("Please send a contact file first using /start")
        return
    
    user_data = converter.user_data[user_id]
    
    if user_data.get('waiting_for_name'):
        base_name = update.message.text.strip()
        user_data['base_name'] = base_name
        user_data['waiting_for_name'] = False
        
        # Update contacts without names
        for i, contact in enumerate(user_data['contacts']):
            if not contact['name']:
                contact['name'] = f"{base_name} {i + 1}"
        
        await update.message.reply_text(f"✅ Base name set to '{base_name}'")
        await show_split_options(update, len(user_data['contacts']))
    
    elif user_data.get('waiting_for_filename'):
        custom_name = update.message.text.strip()
        user_data['custom_filename'] = custom_name
        user_data['waiting_for_filename'] = False
        
        await update.message.reply_text(f"✅ Filename set to '{custom_name}'\n🔄 Creating your VCF files...")
        
        # Process the VCF creation with custom filename
        await create_vcf_files(update, context, user_id)

async def show_split_options(update: Update, total_contacts):
    """Show split options to user"""
    keyboard = [
        [InlineKeyboardButton("35 contacts", callback_data="split_35"),
         InlineKeyboardButton("40 contacts", callback_data="split_40")],
        [InlineKeyboardButton("50 contacts", callback_data="split_50"),
         InlineKeyboardButton("75 contacts", callback_data="split_75")],
        [InlineKeyboardButton("100 contacts", callback_data="split_100"),
         InlineKeyboardButton("150 contacts", callback_data="split_150")],
        [InlineKeyboardButton("200 contacts", callback_data="split_200")],
        [InlineKeyboardButton("📁 Keep all in one file", callback_data="no_split")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f"📊 Found {total_contacts} contacts!\n\nHow would you like to split them?"
    await update.message.reply_text(message, reply_markup=reply_markup)

async def ask_for_filename(update, context, user_id, split_size=None):
    """Ask user for custom filename"""
    user_data = converter.user_data[user_id]
    user_data['split_size'] = split_size
    user_data['waiting_for_filename'] = True
    
    if split_size:
        message = f"📝 Please enter a custom name for your VCF files.\n\nExample: If you enter 'zeno', your files will be named:\n• zeno_1-{split_size}.vcf\n• zeno_{split_size+1}-{split_size*2}.vcf\n\nEnter your preferred name:"
    else:
        message = f"📝 Please enter a custom name for your VCF file.\n\nExample: If you enter 'zeno', your file will be named:\n• zeno_1-{len(user_data['contacts'])}.vcf\n\nEnter your preferred name:"
    
    await update.callback_query.edit_message_text(message)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id not in converter.user_data:
        await query.edit_message_text("❌ Session expired. Please start over with /start")
        return
    
    if query.data == "no_split":
        await ask_for_filename(update, context, user_id)
        
    elif query.data.startswith("split_"):
        chunk_size = int(query.data.split("_")[1])
        await ask_for_filename(update, context, user_id, chunk_size)

async def create_vcf_files(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Create VCF files with custom filename"""
    user_data = converter.user_data[user_id]
    contacts = user_data['contacts']
    custom_name = user_data['custom_filename']
    split_size = user_data.get('split_size')
    
    if not split_size:
        # Single file
        vcf_content = converter.create_vcf_content(contacts)
        vcf_file = StringIO(vcf_content)
        
        filename = f"{custom_name}_1-{len(contacts)}.vcf"
        
        await context.bot.send_document(
            chat_id=update.message.chat_id,
            document=vcf_file,
            filename=filename,
            caption=f"✅ Your VCF file '{filename}' with {len(contacts)} contacts!"
        )
    else:
        # Multiple files
        chunks = converter.split_contacts(contacts, split_size)
        
        for i, chunk in enumerate(chunks, 1):
            vcf_content = converter.create_vcf_content(chunk)
            vcf_file = StringIO(vcf_content)
            
            start_num = (i - 1) * split_size + 1
            end_num = min(i * split_size, len(contacts))
            filename = f"{custom_name}_{start_num}-{end_num}.vcf"
            
            await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=vcf_file,
                filename=filename,
                caption=f"📁 {filename} - {len(chunk)} contacts (#{start_num}-{end_num})"
            )
        
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=f"✅ All done! Created {len(chunks)} VCF files with {len(contacts)} total contacts using name '{custom_name}'"
        )
    
    # Clean up user data
    del converter.user_data[user_id]

def main():
    """Main function to run the bot"""
    # Get bot token from environment or replace with your token
    BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    
    
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("restart", restart))
    application.add_handler(CommandHandler("lord", lord))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Start the bot
    print("🤖 VCF Converter Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
