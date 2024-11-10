import random  # This is random bullshit
import logging
import subprocess
import sys
import os
import re
import time
import concurrent.futures
import discord
from discord.ext import commands, tasks
import docker
import asyncio
from discord import app_commands

TOKEN = ''  # TOKEN HERE
RAM_LIMIT = '2g'
SERVER_LIMIT = 12
database_file = 'database.txt'

# Your user ID
MY_USER_ID = 1135130931661901930

intents = discord.Intents.default()
intents.messages = False
intents.message_content = False

bot = commands.Bot(command_prefix='/', intents=intents)
client = docker.from_env()

# port gen forward module < i forgot this shit in the start
def generate_random_port(): 
    return random.randint(1025, 65535)

def add_to_database(user, container_name, ssh_command):
    with open(database_file, 'a') as f:
        f.write(f"{user}|{container_name}|{ssh_command}\n")

def remove_from_database(ssh_command):
    if not os.path.exists(database_file):
        return
    with open(database_file, 'r') as f:
        lines = f.readlines()
    with open(database_file, 'w') as f:
        for line in lines:
            if ssh_command not in line:
                f.write(line)

async def capture_ssh_session_line(process):
    while True:
        output = await process.stdout.readline()
        if not output:
            break
        output = output.decode('utf-8').strip()
        if "ssh session:" in output:
            return output.split("ssh session:")[1].strip()
    return None

def get_ssh_command_from_database(container_id):
    if not os.path.exists(database_file):
        return None
    with open(database_file, 'r') as f:
        for line in f:
            if container_id in line:
                return line.split('|')[2]
    return None

def get_user_servers(user):
    if not os.path.exists(database_file):
        return []
    servers = []
    with open(database_file, 'r') as f:
        for line in f:
            if line.startswith(user):
                servers.append(line.strip())
    return servers

def count_user_servers(user):
    return len(get_user_servers(user))

def get_container_id_from_database(user):
    servers = get_user_servers(user)
    if servers:
        return servers[0].split('|')[1]
    return None

@bot.event
async def on_ready():
    change_status.start()
    print(f'Bot is ready. Logged in as {bot.user}')
    await bot.tree.sync()

@tasks.loop(seconds=5)
async def change_status():
    try:
        if os.path.exists(database_file):
            with open(database_file, 'r') as f:
                lines = f.readlines()
                instance_count = len(lines)
        else:
            instance_count = 0

        status = f"with {instance_count} Cloud Instances"
        await bot.change_presence(activity=discord.Game(name=status))
    except Exception as e:
        print(f"Failed to update status: {e}")

async def regen_ssh_command(interaction: discord.Interaction, container_name: str):
    user = str(interaction.user)
    container_id = get_container_id_from_database(user, container_name)

    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(description="No active instance found for your user.", color=0xff0000))
        return

    try:
        exec_cmd = await asyncio.create_subprocess_exec("docker", "exec", container_id, "tmate", "-F",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Error executing tmate in Docker container: {e}", color=0xff0000))
        return

    ssh_session_line = await capture_ssh_session_line(exec_cmd)
    if ssh_session_line:
        await interaction.user.send(embed=discord.Embed(description=f"### New SSH Session Command: ```{ssh_session_line}```", color=0x00ff00))
        await interaction.response.send_message(embed=discord.Embed(description="New SSH session generated. Check your DMs for details.", color=0x00ff00))
    else:
        await interaction.response.send_message(embed=discord.Embed(description="Failed to generate new SSH session.", color=0xff0000))

# Admin commands below

@bot.tree.command(name="adminlist", description="List all active servers (admin only)")
async def admin_list(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(embed=discord.Embed(description="You don't have permission to use this command.", color=0xff0000))
        return

    try:
        all_containers = subprocess.check_output(["docker", "ps", "-a", "--format", "{{.ID}}|{{.Names}}"]).decode('utf-8').strip().split("\n")
        embed = discord.Embed(title="All Docker Containers", color=0x00ff00)
        for container in all_containers:
            container_id, container_name = container.split('|')
            embed.add_field(name=container_name, value=f"ID: {container_id}", inline=False)
        await interaction.response.send_message(embed=embed)
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Error listing containers: {e}", color=0xff0000))

@bot.tree.command(name="adminstop", description="Stop a Docker container (admin only)")
@app_commands.describe(container_name="The name of the container to stop")
async def admin_stop(interaction: discord.Interaction, container_name: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(embed=discord.Embed(description="You don't have permission to use this command.", color=0xff0000))
        return

    try:
        subprocess.run(["docker", "stop", container_name], check=True)
        await interaction.response.send_message(embed=discord.Embed(description=f"Container {container_name} stopped successfully.", color=0x00ff00))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Error stopping container {container_name}: {e}", color=0xff0000))

@bot.tree.command(name="adminstart", description="Start a Docker container (admin only)")
@app_commands.describe(container_name="The name of the container to start")
async def admin_start(interaction: discord.Interaction, container_name: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(embed=discord.Embed(description="You don't have permission to use this command.", color=0xff0000))
        return

    try:
        subprocess.run(["docker", "start", container_name], check=True)
        await interaction.response.send_message(embed=discord.Embed(description=f"Container {container_name} started successfully.", color=0x00ff00))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Error starting container {container_name}: {e}", color=0xff0000))

async def deploy_custom_server(interaction: discord.Interaction, image: str, ram: str, cpus: int):
    await interaction.response.send_message(embed=discord.Embed(description="Creating Instance, This takes a few seconds.", color=0x00ff00))

    user = str(interaction.user)
    if count_user_servers(user) >= SERVER_LIMIT:
        await interaction.followup.send(embed=discord.Embed(description="```Error: Instance Limit-reached```", color=0xff0000))
        return

    try:
        container_id = subprocess.check_output([
            "docker", "run", "-itd", "--privileged", "--cap-add=ALL", 
            "--memory", ram, "--cpus", str(cpus), image
        ]).strip().decode('utf-8')
    except subprocess.CalledProcessError as e:
        await interaction.followup.send(embed=discord.Embed(description=f"Error creating Docker container: {e}", color=0xff0000))
        return

    try:
        exec_cmd = await asyncio.create_subprocess_exec("docker", "exec", container_id, "tmate", "-F",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        await interaction.followup.send(embed=discord.Embed(description=f"Error executing tmate in Docker container: {e}", color=0xff0000))
        subprocess.run(["docker", "kill", container_id])
        subprocess.run(["docker", "rm", container_id])
        return

    ssh_session_line = await capture_ssh_session_line(exec_cmd)
    if ssh_session_line:
        await interaction.user.send(embed=discord.Embed(description=f"### Successfully created Instance\nSSH Session Command: ```{ssh_session_line}```\nOS: Custom", color=0x00ff00))
        add_to_database(user, container_id, ssh_session_line)
        await interaction.followup.send(embed=discord.Embed(description="Instance created successfully. Check your DMs for details.", color=0x00ff00))
    else:
        await interaction.followup.send(embed=discord.Embed(description="Something went wrong or the Instance is taking longer than expected. If this problem continues, Contact Support.", color=0xff0000))
        subprocess.run(["docker", "kill", container_id])
        subprocess.run(["docker", "rm", container_id])

@bot.tree.command(name="deploy", description="Deploy a custom server with specific RAM and CPU (admin only)")
@app_commands.describe(image="Docker image", ram="Amount of RAM (e.g., '2g')", cpus="Number of CPUs (e.g., '2')")
async def deploy(interaction: discord.Interaction, image: str, ram: str, cpus: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(embed=discord.Embed(description="You don't have permission to use this command.", color=0xff0000))
        return

    # Deploy custom server logic
    await deploy_custom_server(interaction, image, ram, cpus)

# Advanced ping command
@bot.tree.command(name="ping", description="Check the bot's latency and WebSocket ping.")
async def ping(interaction: discord.Interaction):
    latency = bot.latency * 1000  # Convert to milliseconds
    websocket_ping = bot.ws.ping  # WebSocket ping in milliseconds
    embed = discord.Embed(title="Pong!", color=0x00ff00)
    embed.add_field(name="Bot Latency", value=f"{latency:.2f} ms", inline=False)
    embed.add_field(name="WebSocket Ping", value=f"{websocket_ping} ms", inline=False)
    await interaction.response.send_message(embed=embed)

# Shutdown the bot command
@bot.tree.command(name="shutdown", description="Shut down the bot (admin only)")
async def shutdown(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(embed=discord.Embed(description="You don't have permission to use this command.", color=0xff0000))
        return

    await interaction.response.send_message(embed=discord.Embed(description="Shutting down the bot...", color=0x00ff00))
    await bot.close()

# Start the bot
bot.run(TOKEN)
