const mysql = require("mysql2/promise");
require("dotenv").config();

async function testConnection() {
  try {
    console.log("Testing MySQL connection...");

    const connection = await mysql.createConnection({
      host: process.env.DB_HOST,
      user: process.env.DB_USER,
      password: process.env.DB_PASSWORD,
    });

    console.log("✅ MySQL connection successful!");

    // Show databases
    const [databases] = await connection.execute("SHOW DATABASES");
    console.log("Available databases:");
    databases.forEach((db) => console.log("-", db.Database));

    await connection.end();
  } catch (error) {
    console.error("❌ MySQL connection failed:");
    console.error("Error:", error.message);
    console.log("Please check your MySQL password in the .env file");
  }
}

testConnection();
