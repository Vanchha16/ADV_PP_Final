# Final Project: ADV PP

## 1. Overview

Build a mini e-commerce web application using **Python** where customers can browse products, manage a shopping cart, and place orders with KHQR payment. An administrative interface is also required to manage product inventory and view order history.

---

## 2. Project Scenario

You are tasked with building a web store named **....Shop** supporting the following key flows:

- **Customers (Guests):** Browse product listings, view details, share to social channels, add items to a cart, and complete checkout using KHQR.
- **Admin:** Manage products (view, add, edit, delete) and view order history.

---

## 3. Functional Requirements

### 3.1 Public (Customer) Pages

1. **Home Page**
   - Display a grid/list of products showing: Name, Price, Description, and Thumbnail.
   - Actions: **View Details**, **Add to Cart**.

2. **Product Detail Page**
   - Display complete product details: Full description, price, stock status, and image.
   - Quantity selector with **Add to Cart** action.
   - **Share Buttons**: Share product link to **Facebook** and **Telegram**.

3. **Cart Page**
   - Display cart items with quantity, unit price, subtotal, and total amount.
   - Update quantity or remove items from the cart.
   - **Proceed to Checkout** button.

4. **Checkout Page**
   - Guest customer information form:
     - Full Name
     - Email Address
     - Phone Number
     - Shipping Address
   - **KHQR Payment**: Display KHQR code (Bakong / KHQR) for payment scanning.
   - Save the completed order and customer details into the database.

5. **Order Confirmation Page**
   - Display order success message.
   - Show summary with **Order ID**, customer details, and **Total Amount**.

---

### 3.2 Admin Pages

1. **Admin Product List**
   - Display all products in a table view with: ID, Name, Price, Stock, and Status (e.g., Active/Inactive).
   - Actions: **Add New Product**, **Edit**, and **Delete**.

2. **Admin Product Form (Create / Edit)**
   - Input fields:
     - Name
     - Description
     - Price
     - Stock Quantity
     - Image
     - Status
   - Save or update product records.

3. **Admin Order History**
   - Display customer orders in a table view with: Order ID, Customer Name, Phone Number, Total Amount, and Order Date.
   - Action: **View Order Details** (show purchased items, quantities, subtotal, and shipping address).

---

## 4. Submission Requirements

Submit your completed project with the following deliverables:

- **Live Demo**: Hosted/deployed project URL.
- **Admin URL**: username, password
- **Source Code**: GitHub repository link (public or accessible).
- **Video Demo**: Short walkthrough video demonstrating all features and workflow.
- **Submission Method**: Send To Telegram message Topic.

**Submission Format Example:**
> `1. Heng Dara (Home Page and Product Detail Page)`
>
> `2. ......`
